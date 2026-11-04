from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx

KST = timezone(timedelta(hours=9), "KST")

DISTRICTS: tuple[str, ...] = (
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구",
    "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구",
    "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
)

CONDITIONS: tuple[str, ...] = ("clear", "partly cloudy", "cloudy", "rain", "snow", "fog")

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.978"
    "&current=temperature_2m,relative_humidity_2m,weather_code"
)

# WMO weather interpretation codes -> our small vocabulary.
_WMO = {0: "clear", 1: "clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog"}


def _seed(*parts: object) -> int:
    # hashlib, not hash(): str hashes are randomized per process and values must be stable across restarts.
    return int.from_bytes(hashlib.sha256(repr(parts).encode()).digest()[:8], "big")


def _condition_from_code(code: int) -> str:
    if code in _WMO:
        return _WMO[code]
    if 51 <= code <= 67 or 80 <= code <= 82 or code >= 95:
        return "rain"
    if 71 <= code <= 77 or 85 <= code <= 86:
        return "snow"
    return "cloudy"


def _check_district(district: str) -> None:
    if district not in DISTRICTS:
        raise ValueError(f"unknown district: {district!r}")


def _dummy(district: str) -> dict:
    now = datetime.now(KST)
    s = _seed(district, now.strftime("%Y-%m-%dT%H"))
    return {
        "district": district,
        "temperature_c": round(-10 + (s % 450) / 10, 1),  # -10.0 .. 34.9
        "humidity_pct": 20 + (s >> 16) % 76,  # 20 .. 95
        "condition": CONDITIONS[(s >> 32) % len(CONDITIONS)],
        "source": "dummy",
    }


def get_current_weather(district: str, fetch: Callable[[], dict] | None = None) -> dict:
    _check_district(district)
    if fetch is not None:
        try:
            cur = fetch()["current"]
            return {
                "district": district,
                "temperature_c": float(cur["temperature_2m"]),
                "humidity_pct": int(cur["relative_humidity_2m"]),
                "condition": _condition_from_code(int(cur["weather_code"])),
                "source": "open-meteo",
            }
        except Exception:  # any failure (network, shape, parse) falls back to dummy data
            pass
    return _dummy(district)


def fetch_open_meteo() -> dict:
    """Blocking GET with a 3 s timeout; raises on any failure (the caller falls back to dummy data)."""
    resp = httpx.get(OPEN_METEO_URL, timeout=3.0)
    resp.raise_for_status()
    return resp.json()


def get_forecast(days: int) -> list[dict]:
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
        raise ValueError("days must be an integer between 1 and 7")
    today = datetime.now(KST).date()
    out = []
    for i in range(days):
        d = today + timedelta(days=i)
        s = _seed("forecast", d.isoformat())
        low = round(-10 + (s % 300) / 10, 1)
        out.append({
            "date": d.isoformat(),
            "min_c": low,
            "max_c": round(low + 3 + (s >> 16) % 100 / 10, 1),
            "condition": CONDITIONS[(s >> 32) % len(CONDITIONS)],
        })
    return out
