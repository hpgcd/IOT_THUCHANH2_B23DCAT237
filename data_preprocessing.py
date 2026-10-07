"""Clean telemetry, detect outliers, aggregate by minute and create features."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import numpy as np
import pandas as pd

from config import SETTINGS


SENSORS = ["temperature", "humidity"]
CONTINUOUS = SENSORS + ["rssi"]
NUMERIC = CONTINUOUS + ["motion"]


def load_influx_data(hours: int) -> pd.DataFrame:
    """Read raw points from the time-series database over a fixed time window."""
    query = (
        f"from(bucket: {json.dumps(SETTINGS.influx_bucket)}) "
        f"|> range(start: -{hours}h) "
        f'|> filter(fn: (r) => r._measurement == "{SETTINGS.raw_measurement}")'
    )
    rows = {}
    with InfluxDBClient(url=SETTINGS.influx_url, token=SETTINGS.influx_token, org=SETTINGS.influx_org, timeout=3000) as client:
        for table in client.query_api().query(query):
            for record in table.records:
                field = record.get_field()
                if field not in NUMERIC:
                    continue
                key = (record.get_time().isoformat(), record.values.get("device_id", ""), record.values.get("location", ""))
                row = rows.setdefault(key, {"time": key[0], "device_id": key[1], "location": key[2]})
                row[field] = record.get_value()
    return pd.DataFrame(rows.values())


def write_processed_influx(processed: pd.DataFrame) -> None:
    """Write minute-level rows using stable timestamps, so reruns are idempotent."""
    columns = CONTINUOUS + [
        "temperature_rolling_3m", "humidity_rolling_3m", "temperature_delta",
        "heat_index_c", "temperature_normalized", "humidity_normalized",
        "motion_ratio",
    ]
    points = []
    for row in processed.itertuples(index=False):
        values = row._asdict()
        point = (
            Point(SETTINGS.processed_measurement)
            .tag("device_id", values["device_id"])
            .tag("location", values["location"])
            .time(values["time"].to_pydatetime(), WritePrecision.NS)
        )
        for column in columns:
            value = values[column]
            if pd.notna(value):
                point.field(column, float(value))
        point.field("motion", int(values["motion"]))
        point.field("motion_events", int(values["motion_events"]))
        points.append(point)
    with InfluxDBClient(url=SETTINGS.influx_url, token=SETTINGS.influx_token, org=SETTINGS.influx_org, timeout=3000) as client:
        client.write_api(write_options=SYNCHRONOUS).write(bucket=SETTINGS.influx_bucket, org=SETTINGS.influx_org, record=points)


def generate_sample(path: Path, count: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(237)
    start = datetime.now(timezone.utc) - timedelta(seconds=5 * count)
    index = np.arange(count)
    sample = pd.DataFrame({
        "time": [(start + timedelta(seconds=5 * int(i))).isoformat() for i in index],
        "device_id": "ESP32-PIR-SAMPLE-B23DCAT237",
        "location": "lab_ptit",
        "temperature": 25 + 1.8 * np.sin(index / 14) + rng.normal(0, 0.4, count),
        "humidity": 53 + 6 * np.sin(index / 19) + rng.normal(0, 1.2, count),
        "motion": ((index // 20) % 2).astype(int),
        "rssi": rng.integers(-62, -46, count),
        "sequence": index + 1,
        "uptime_s": index * 5,
        "sent_at_ms": 0,
        "mqtt_latency_ms": np.nan,
    })
    sample.loc[[17, 62, 119, 177], "temperature"] = np.nan
    sample.loc[[22, 72, 135, 188], "humidity"] = np.nan
    sample.loc[[29, 74, 129], "temperature"] = [45, -4, 49]
    sample.loc[[51, 151], "humidity"] = [97, 2]
    path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(path, index=False)
    return sample


def heat_index_c(temp: pd.Series, humidity: pd.Series) -> pd.Series:
    """Rothfusz approximation for warm conditions; otherwise ambient temperature."""
    f = temp * 9 / 5 + 32
    rh = humidity
    heat_f = (
        -42.379 + 2.04901523 * f + 10.14333127 * rh
        - 0.22475541 * f * rh - 0.00683783 * f**2
        - 0.05481717 * rh**2 + 0.00122874 * f**2 * rh
        + 0.00085282 * f * rh**2 - 0.00000199 * f**2 * rh**2
    )
    return pd.Series(np.where(temp >= 26.7, (heat_f - 32) * 5 / 9, temp), index=temp.index)


def process_dataframe(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {"time", "device_id", "location", *NUMERIC}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"CSV thieu cot: {', '.join(sorted(missing))}")
    data = raw.copy()
    data["time"] = pd.to_datetime(data["time"], utc=True, errors="coerce")
    data = data.dropna(subset=["time"]).sort_values(["device_id", "time"])
    if data.empty:
        raise ValueError("Khong co timestamp hop le")
    for column in NUMERIC:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    report = {"input_rows": len(data), "missing_before": data[NUMERIC].isna().sum().to_dict(), "iqr": {}, "zscore": {}}
    for _device, indices in data.groupby("device_id").groups.items():
        subset = data.loc[indices].sort_values("time")
        for column in CONTINUOUS:
            data.loc[subset.index, column] = subset[column].interpolate(limit_direction="both").to_numpy()
    data["motion"] = data["motion"].fillna(0).clip(0, 1).round().astype(int)
    report["missing_after"] = data[NUMERIC].isna().sum().to_dict()

    for column in SENSORS:
        details = {}
        z_total = 0
        for device_id, indices in data.groupby("device_id").groups.items():
            series = data.loc[indices, column].dropna()
            q1, q3 = series.quantile([0.25, 0.75])
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = data.loc[indices, column].notna() & ((data.loc[indices, column] < lower) | (data.loc[indices, column] > upper))
            std = series.std(ddof=0)
            z_total += int(((series - series.mean()).abs() / std > 3).sum()) if std > 0 else 0
            details[device_id] = {"q1": float(q1), "q3": float(q3), "lower": float(lower), "upper": float(upper), "count": int(outliers.sum())}
            data.loc[outliers[outliers].index, column] = np.nan
        report["iqr"][column] = {"count": sum(item["count"] for item in details.values()), "per_device": details}
        report["zscore"][column] = z_total
        for _device, indices in data.groupby("device_id").groups.items():
            subset = data.loc[indices].sort_values("time")
            data.loc[subset.index, column] = subset[column].interpolate(limit_direction="both").to_numpy()

    pieces = []
    for (device_id, location), group in data.groupby(["device_id", "location"]):
        indexed = group.set_index("time")
        minute = indexed[CONTINUOUS].resample("1min").mean()
        motion = indexed["motion"]
        counts = motion.resample("1min").count()
        minute = minute[counts > 0]
        if minute.empty:
            continue
        minute = minute.interpolate(limit_direction="both")
        minute["motion"] = motion.resample("1min").max().loc[minute.index].astype(int)
        minute["motion_ratio"] = motion.resample("1min").mean().loc[minute.index]
        starts = (motion.eq(1) & motion.shift(fill_value=0).eq(0)).astype(int)
        minute["motion_events"] = starts.resample("1min").sum().loc[minute.index].astype(int)
        minute["device_id"] = device_id
        minute["location"] = location
        minute["temperature_rolling_3m"] = minute["temperature"].rolling(3, min_periods=1).mean()
        minute["humidity_rolling_3m"] = minute["humidity"].rolling(3, min_periods=1).mean()
        minute["temperature_delta"] = minute["temperature"].diff().fillna(0)
        minute["heat_index_c"] = heat_index_c(minute["temperature"], minute["humidity"])
        for column in SENSORS:
            minimum, maximum = minute[column].min(), minute[column].max()
            minute[f"{column}_normalized"] = (minute[column] - minimum) / (maximum - minimum) if maximum > minimum else 0.0
        pieces.append(minute.reset_index())
    if not pieces:
        raise ValueError("Khong co du lieu de resample")
    processed = pd.concat(pieces, ignore_index=True).sort_values(["device_id", "time"])
    report["output_rows"] = len(processed)
    return processed, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess IoT telemetry")
    parser.add_argument("--source", choices=["auto", "influx", "csv", "sample"], default="auto")
    parser.add_argument("--hours", type=int, default=24, help="InfluxDB lookback window")
    parser.add_argument("--no-db-write", action="store_true", help="only write processed CSV")
    args = parser.parse_args()
    if args.hours < 1:
        parser.error("--hours must be positive")
    SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
    raw_path = SETTINGS.data_dir / SETTINGS.raw_csv_name
    sample_path = SETTINGS.data_dir / SETTINGS.sample_csv_name
    raw = pd.DataFrame()
    source = ""
    is_sample = False
    if args.source in ("auto", "influx"):
        try:
            raw = load_influx_data(args.hours)
            if not raw.empty:
                source = f"InfluxDB (last {args.hours} hours)"
        except Exception as exc:
            if args.source == "influx":
                raise SystemExit(f"Khong doc duoc InfluxDB: {exc}") from exc
            print(f"[InfluxDB] Khong doc duoc; thu CSV: {exc}")
    if args.source == "influx" and raw.empty:
        raise SystemExit("InfluxDB khong co du lieu trong khoang thoi gian chon")
    if args.source in ("auto", "csv") and raw.empty and raw_path.exists() and raw_path.stat().st_size:
        raw = pd.read_csv(raw_path)
        source = f"{raw_path} (CSV MQTT)"
    if args.source == "csv" and raw.empty:
        raise SystemExit(f"Khong co {SETTINGS.raw_csv_name}")
    if args.source == "sample" or raw.empty:
        raw = generate_sample(sample_path)
        source = f"{sample_path} (du lieu mo phong)"
        is_sample = True
    print(f"Nguon: {source}; thiet bi DEMO la du lieu mo phong")
    processed, report = process_dataframe(raw)
    output = SETTINGS.data_dir / SETTINGS.processed_csv_name
    processed.to_csv(output, index=False)
    print("\nBUOC 1 - GIA TRI THIEU")
    for column in NUMERIC:
        print(f"  {column}: {report['missing_before'][column]} -> {report['missing_after'][column]}")
    print("\nBUOC 2a - OUTLIER IQR / BUOC 2b - Z-SCORE")
    for column in SENSORS:
        info = report["iqr"][column]
        print(f"  {column}: IQR={info['count']}; Z>3={report['zscore'][column]}")
        for device_id, device_info in info["per_device"].items():
            print(f"    {device_id}: Q1={device_info['q1']:.2f}, Q3={device_info['q3']:.2f}, gioi han [{device_info['lower']:.2f}, {device_info['upper']:.2f}], outlier={device_info['count']}")
    print(f"\nBUOC 3 - RESAMPLE 1 PHUT: {report['input_rows']} -> {report['output_rows']} ban ghi")
    print("BUOC 4 - DAC TRUNG: rolling 3 phut, delta nhiet do, heat index, PIR ratio/events")
    print("BUOC 5 - CHUAN HOA MIN-MAX: temperature, humidity")
    print(f"Da luu: {output}")
    if not is_sample and not args.no_db_write:
        try:
            write_processed_influx(processed)
            print(f"Da luu InfluxDB: measurement {SETTINGS.processed_measurement} ({len(processed)} ban ghi)")
        except Exception as exc:
            print(f"[InfluxDB] Khong ghi duoc du lieu da xu ly; CSV van da luu: {exc}")


if __name__ == "__main__":
    main()
