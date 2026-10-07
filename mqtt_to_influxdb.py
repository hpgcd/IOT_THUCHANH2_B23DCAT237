"""Subscribe to MQTT, save valid data to CSV, and replay it into InfluxDB."""

import csv
from datetime import datetime, timezone
import json
import os
import threading
import time

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import paho.mqtt.client as mqtt

from config import SETTINGS
from telemetry import validate_payload


FIELDS = [
    "time", "device_id", "location", "temperature", "humidity", "motion",
    "rssi", "sequence", "uptime_s", "sent_at_ms", "mqtt_latency_ms",
]
METRIC_FIELDS = ["stored_at", "device_id", "sequence", "mqtt_latency_ms", "db_write_ms", "e2e_ms"]


class Collector:
    def __init__(self) -> None:
        SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = SETTINGS.data_dir / SETTINGS.raw_csv_name
        self.metrics_path = SETTINGS.data_dir / SETTINGS.metrics_csv_name
        self.state_path = SETTINGS.data_dir / SETTINGS.sync_state_name
        self.synced = self._read_state() if self.csv_path.exists() else 0
        self.influx = InfluxDBClient(url=SETTINGS.influx_url, token=SETTINGS.influx_token, org=SETTINGS.influx_org, timeout=3000)
        self.writer = self.influx.write_api(write_options=SYNCHRONOUS)
        self.count = 0
        self.csv_lock = threading.Lock()
        self.sync_requested = threading.Event()
        self.stopping = threading.Event()

    def _read_state(self) -> int:
        try:
            value = int(json.loads(self.state_path.read_text(encoding="utf-8"))["synced_rows"])
            return max(0, value)
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return 0

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"synced_rows": self.synced}), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _append_csv(self, row: dict) -> None:
        new_file = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
            output.flush()
            os.fsync(output.fileno())

    def _append_metrics(self, row: dict, db_ms: float) -> str:
        now = datetime.now(timezone.utc)
        sent_ms = int(row["sent_at_ms"])
        e2e_ms = now.timestamp() * 1000 - sent_ms if sent_ms else None
        metric = {
            "stored_at": now.isoformat(),
            "device_id": row["device_id"],
            "sequence": row["sequence"],
            "mqtt_latency_ms": row["mqtt_latency_ms"],
            "db_write_ms": round(db_ms, 1),
            "e2e_ms": round(e2e_ms, 1) if e2e_ms is not None and 0 <= e2e_ms < 86400000 else "",
        }
        new_file = not self.metrics_path.exists() or self.metrics_path.stat().st_size == 0
        with self.metrics_path.open("a", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=METRIC_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(metric)
        return str(metric["e2e_ms"]) if metric["e2e_ms"] != "" else "n/a"

    def _write_influx(self, row: dict) -> None:
        point = (
            Point(SETTINGS.raw_measurement)
            .tag("device_id", row["device_id"])
            .tag("location", row["location"])
            .field("temperature", float(row["temperature"]))
            .field("humidity", float(row["humidity"]))
            .field("motion", int(row["motion"]))
            .field("rssi", int(float(row["rssi"])))
            .field("sequence", int(row["sequence"]))
            .field("uptime_s", int(row["uptime_s"]))
            .time(datetime.fromisoformat(row["time"]), WritePrecision.NS)
        )
        if int(row["sent_at_ms"]):
            point.field("sent_at_ms", int(row["sent_at_ms"]))
        if row["mqtt_latency_ms"]:
            point.field("mqtt_latency_ms", float(row["mqtt_latency_ms"]))
        self.writer.write(bucket=SETTINGS.influx_bucket, org=SETTINGS.influx_org, record=point)

    def flush_pending(self) -> None:
        with self.csv_lock:
            if not self.csv_path.exists():
                return
            with self.csv_path.open("r", encoding="utf-8", newline="") as source:
                pending = [(index, row) for index, row in enumerate(csv.DictReader(source)) if index >= self.synced]
        for index, row in pending:
            if self.stopping.is_set():
                break
            try:
                started = time.perf_counter()
                self._write_influx(row)
                db_ms = (time.perf_counter() - started) * 1000
            except Exception as exc:
                print(f"[InfluxDB] Ghi that bai, CSV da luu de thu lai: {exc}", flush=True)
                break
            self.synced = index + 1
            self._save_state()
            e2e = self._append_metrics(row, db_ms)
            print(f"[InfluxDB] Da dong bo ban ghi {self.synced} (ghi {db_ms:.1f} ms; E2E {e2e} ms)", flush=True)

    def sync_loop(self) -> None:
        while not self.stopping.is_set():
            self.sync_requested.wait(timeout=5)
            self.sync_requested.clear()
            if not self.stopping.is_set():
                self.flush_pending()

    def on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code == 0:
            client.subscribe(SETTINGS.mqtt_topic, qos=1)
            print(f"[MQTT] Da ket noi {SETTINGS.mqtt_host}:{SETTINGS.mqtt_port}; topic {SETTINGS.mqtt_topic}", flush=True)
            self.sync_requested.set()
        else:
            print(f"[MQTT] Ket noi that bai: {reason_code}", flush=True)

    def on_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            print("[MQTT] Mat ket noi; dang thu ket noi lai...", flush=True)

    def on_message(self, _client, _userdata, message) -> None:
        received = datetime.now(timezone.utc)
        try:
            row = validate_payload(message.payload)
        except ValueError as exc:
            print(f"[CANH BAO] Du lieu khong hop le: {exc}", flush=True)
            return
        row["time"] = received.isoformat()
        sent_ms = row["sent_at_ms"]
        latency = received.timestamp() * 1000 - sent_ms if sent_ms else None
        row["mqtt_latency_ms"] = round(latency, 1) if latency is not None and 0 <= latency < 86400000 else ""
        with self.csv_lock:
            self._append_csv(row)
        self.sync_requested.set()
        self.count += 1
        print(
            f"[{received.isoformat()}] #{self.count} {row['device_id']} "
            f"T={row['temperature']:.1f}C RH={row['humidity']:.1f}% "
            f"PIR={row['motion']} RSSI={row['rssi']:.0f}dBm "
            f"seq={row['sequence']} MQTT={row['mqtt_latency_ms'] or 'n/a'}ms",
            flush=True,
        )

    def run(self) -> None:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bai2-collector-{os.getpid()}")
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        print("[MQTT] Dang ket noi... Ctrl+C de dung", flush=True)
        worker = threading.Thread(target=self.sync_loop, name="influx-sync", daemon=True)
        worker.start()
        self.sync_requested.set()
        try:
            client.connect_async(SETTINGS.mqtt_host, SETTINGS.mqtt_port, keepalive=60)
            client.loop_forever(retry_first_connection=True)
        finally:
            self.stopping.set()
            self.sync_requested.set()
            worker.join()
            self.influx.close()


if __name__ == "__main__":
    Collector().run()
