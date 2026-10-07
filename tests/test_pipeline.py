import json
import unittest

import numpy as np
import pandas as pd

from data_preprocessing import process_dataframe
from telemetry import validate_payload


BASE = {
    "device_id": "ESP32-PIR-B23DCAT237",
    "location": "lab_ptit",
    "temperature": 25.0,
    "humidity": 50.0,
    "motion": 0,
    "rssi": -51,
    "sequence": 1,
    "uptime_s": 5,
    "sent_at_ms": 0,
}


class TelemetryTests(unittest.TestCase):
    def test_valid_message(self):
        self.assertEqual(validate_payload(json.dumps(BASE).encode())["temperature"], 25.0)

    def test_rejects_invalid_and_nonfinite_values(self):
        for update in ({"temperature": 80}, {"humidity": float("nan")}, {"sequence": True}, {"motion": 2}, {"motion": True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_payload(json.dumps({**BASE, **update}))


class PreprocessingTests(unittest.TestCase):
    def test_missing_and_outlier_are_cleaned(self):
        temperatures = [25.0] * 35
        temperatures[5] = np.nan
        temperatures[18] = 55.0
        frame = pd.DataFrame({
            "time": pd.date_range("2026-10-07", periods=35, freq="5s", tz="UTC"),
            "device_id": [BASE["device_id"]] * 35,
            "location": ["lab_ptit"] * 35,
            "temperature": temperatures,
            "humidity": [50.0] * 35,
            "motion": [0] * 4 + [1] * 4 + [0] * 10 + [1] * 4 + [0] * 13,
            "rssi": [-51] * 35,
        })
        result, report = process_dataframe(frame)
        self.assertEqual(report["missing_before"]["temperature"], 1)
        self.assertEqual(report["missing_after"]["temperature"], 0)
        self.assertEqual(report["iqr"]["temperature"]["count"], 1)
        self.assertTrue((result["temperature"] == 25.0).all())
        self.assertTrue(result["temperature_normalized"].eq(0).all())
        self.assertEqual(len(result), 3)
        self.assertEqual(int(result["motion_events"].sum()), 2)
        self.assertTrue(result["motion_ratio"].between(0, 1).all())

    def test_devices_keep_separate_baselines(self):
        frame = pd.DataFrame({
            "time": list(pd.date_range("2026-10-07", periods=10, freq="5s", tz="UTC")) * 2,
            "device_id": ["ESP32-A"] * 10 + ["ESP32-B"] * 10,
            "location": ["lab_ptit"] * 20,
            "temperature": [10.0] * 10 + [50.0] * 10,
            "humidity": [50.0] * 20,
            "motion": [0] * 10 + [1] * 10,
            "rssi": [-51] * 20,
        })
        result, report = process_dataframe(frame)
        self.assertEqual(report["iqr"]["temperature"]["count"], 0)
        self.assertEqual(set(result["temperature"]), {10.0, 50.0})


if __name__ == "__main__":
    unittest.main()
