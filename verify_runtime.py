"""Read-only check that InfluxDB contains the collector's telemetry."""

import csv
import json

from influxdb_client import InfluxDBClient

from config import SETTINGS


def main() -> None:
    raw_path = SETTINGS.data_dir / SETTINGS.raw_csv_name
    state_path = SETTINGS.data_dir / SETTINGS.sync_state_name
    if not raw_path.exists():
        raise SystemExit(f"No {SETTINGS.raw_csv_name}; run the collector and a publisher first")
    with raw_path.open(encoding="utf-8", newline="") as source:
        local_count = sum(1 for _ in csv.DictReader(source))
    synced = json.loads(state_path.read_text(encoding="utf-8"))["synced_rows"] if state_path.exists() else 0
    query = (
        f'from(bucket: "{SETTINGS.influx_bucket}") '
        '|> range(start: -24h) '
        f'|> filter(fn: (r) => r._measurement == "{SETTINGS.raw_measurement}" and r._field == "temperature") '
        '|> count()'
    )
    with InfluxDBClient(url=SETTINGS.influx_url, token=SETTINGS.influx_token, org=SETTINGS.influx_org) as client:
        tables = client.query_api().query(query)
        db_count = sum(int(record.get_value()) for table in tables for record in table.records)
        processed_query = query.replace(f'r._measurement == "{SETTINGS.raw_measurement}"', f'r._measurement == "{SETTINGS.processed_measurement}"')
        processed_tables = client.query_api().query(processed_query)
        processed_db_count = sum(int(record.get_value()) for table in processed_tables for record in table.records)
        bucket = client.buckets_api().find_bucket_by_name(SETTINGS.influx_bucket)
    if bucket is None:
        raise SystemExit(f"Bucket {SETTINGS.influx_bucket} not found")
    retention = bucket.retention_rules[0].every_seconds if bucket.retention_rules else 0
    print(f"CSV rows: {local_count}; synced cursor: {synced}; Influx temperature rows (24h): {db_count}")
    print(f"Processed Influx rows (24h): {processed_db_count}")
    print(f"Bucket: {bucket.name}; retention: {retention} seconds")
    if synced != local_count or db_count < local_count or retention != 7 * 24 * 3600:
        raise SystemExit("Runtime verification failed")
    print("Runtime verification passed")


if __name__ == "__main__":
    main()
