"""Publish clearly marked synthetic MQTT telemetry for an end-to-end smoke test."""

import argparse
import json
import math
import os
import time

import paho.mqtt.client as mqtt

from config import SETTINGS


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish synthetic IoT telemetry")
    parser.add_argument("--count", type=int, default=20, help="number of messages")
    parser.add_argument("--interval", type=float, default=5, help="seconds between messages")
    args = parser.parse_args()
    if args.count < 1 or args.interval <= 0:
        parser.error("--count and --interval must be positive")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bai2-demo-{os.getpid()}")
    client.connect(SETTINGS.mqtt_host, SETTINGS.mqtt_port, keepalive=60)
    client.loop_start()
    try:
        for sequence in range(1, args.count + 1):
            payload = {
                "device_id": "ESP32-PIR-DEMO-B23DCAT237",
                "location": "lab_ptit",
                "temperature": round(25 + 3 * math.sin(sequence / 4), 2),
                "humidity": round(52 + 8 * math.sin(sequence / 6), 2),
                "motion": 1 if ((sequence - 1) // 3) % 2 else 0,
                "rssi": -51,
                "sequence": sequence,
                "uptime_s": int((sequence - 1) * args.interval),
                "sent_at_ms": int(time.time() * 1000),
            }
            info = client.publish(SETTINGS.mqtt_topic, json.dumps(payload), qos=1)
            info.wait_for_publish(timeout=10)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed: {info.rc}")
            print(f"[DEMO] Sent #{sequence}: {payload}", flush=True)
            if sequence < args.count:
                time.sleep(args.interval)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
