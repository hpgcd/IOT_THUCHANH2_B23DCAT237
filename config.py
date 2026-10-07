"""Shared configuration for the collector, preprocessing script and dashboard."""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))
ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("MQTT_HOST", "broker.hivemq.com")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_topic: str = os.getenv("MQTT_TOPIC", "iot/B23DCAT237/esp32/pir/telemetry")
    influx_url: str = os.getenv("INFLUX_URL", "http://localhost:8086")
    influx_org: str = os.getenv("INFLUX_ORG", "ptit")
    influx_bucket: str = os.getenv("INFLUX_BUCKET", "iot_sensor_data")
    influx_token: str = os.getenv("INFLUX_TOKEN", "local-dev-token-change-me")
    data_dir: Path = ROOT / os.getenv("DATA_DIR", "data")
    raw_measurement: str = "pir_sensor_data"
    processed_measurement: str = "pir_sensor_data_processed"
    raw_csv_name: str = "pir_raw_data.csv"
    sample_csv_name: str = "pir_sample_raw_data.csv"
    processed_csv_name: str = "pir_processed_data.csv"
    metrics_csv_name: str = "pir_write_metrics.csv"
    sync_state_name: str = "pir_influx_synced.json"


SETTINGS = Settings()
