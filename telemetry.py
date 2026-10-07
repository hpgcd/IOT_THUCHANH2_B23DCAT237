"""Validate one ESP32 telemetry message before persisting it."""

import json
import math
import re


TAG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RANGES = {
    "temperature": (-40.0, 60.0),
    "humidity": (0.0, 100.0),
    "rssi": (-120.0, 0.0),
}


def validate_payload(payload: bytes | str) -> dict:
    try:
        item = json.loads(payload)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("JSON khong hop le") from exc
    if not isinstance(item, dict):
        raise ValueError("Ban tin phai la JSON object")

    result = {}
    for name in ("device_id", "location"):
        value = item.get(name)
        if not isinstance(value, str) or not TAG.fullmatch(value):
            raise ValueError(f"{name} khong hop le")
        result[name] = value

    for name, (minimum, maximum) in RANGES.items():
        value = item.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} phai la so")
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{name} ngoai pham vi [{minimum}, {maximum}]: {value}")
        result[name] = float(value)

    motion = item.get("motion")
    if isinstance(motion, bool) or not isinstance(motion, int) or motion not in (0, 1):
        raise ValueError("motion phai la 0 hoac 1")
    result["motion"] = motion

    for name in ("sequence", "uptime_s"):
        value = item.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} phai la so nguyen khong am")
        result[name] = value

    sent_at_ms = item.get("sent_at_ms", 0)
    if isinstance(sent_at_ms, bool) or not isinstance(sent_at_ms, int) or sent_at_ms < 0:
        raise ValueError("sent_at_ms khong hop le")
    result["sent_at_ms"] = sent_at_ms
    return result
