import pytest
import seoul_weather.__main__ as weather_main
from calculator.tools import add, subtract, multiply, divide, evaluate
from common.server import build_parser
from seoul_weather.tools import DISTRICTS, get_current_weather, get_forecast
from seoul_clock.tools import now_kst, convert_timezone


def test_arith():
    assert (add(2, 3), subtract(2, 3), multiply(4, 2.5), divide(7, 2)) == (5, -1, 10, 3.5)
    with pytest.raises(ValueError): divide(1, 0)


@pytest.mark.parametrize("expr,val", [("1+2*3", 7), ("(1+2)*3", 9), ("-2**2", -4), ("7//2", 3), ("7%4", 3), ("2**10", 1024)])
def test_evaluate(expr, val):
    assert evaluate(expr) == val


@pytest.mark.parametrize("expr", ["__import__('os')", "a+1", "1 if 1 else 2", "[1]", "2**10**10", "9" * 201, "1/0", "lambda: 1", "().__class__"])
def test_evaluate_rejects(expr):
    with pytest.raises(ValueError): evaluate(expr)


def test_weather():
    assert len(DISTRICTS) == 25 and "강남구" in DISTRICTS
    w = get_current_weather("강남구")
    assert w["district"] == "강남구" and isinstance(w["temperature_c"], float) and w["source"] == "dummy"
    with pytest.raises(ValueError): get_current_weather("부산")
    assert len(get_forecast(3)) == 3
    for bad in (0, 8):
        with pytest.raises(ValueError): get_forecast(bad)


def test_weather_open_meteo_and_fallback():
    live = get_current_weather("중구", fetch=lambda: {"current": {"temperature_2m": 3.5, "relative_humidity_2m": 40, "weather_code": 0}})
    assert live["source"] == "open-meteo" and live["temperature_c"] == 3.5
    def boom(): raise OSError("offline")
    assert get_current_weather("중구", fetch=boom)["source"] == "dummy"


def test_clock():
    assert now_kst().endswith("+09:00")
    assert convert_timezone("2026-11-05T09:00:00+09:00", "UTC") == "2026-11-05T00:00:00+00:00"
    assert convert_timezone("2026-11-05T09:00:00", "Asia/Tokyo") == "2026-11-05T09:00:00+09:00"
    assert convert_timezone("2026-11-05T09:00:00+09:00", "+05:30") == "2026-11-05T05:30:00+05:30"
    with pytest.raises(ValueError): convert_timezone("2026-11-05T09:00:00", "Mars/Base")


def test_open_meteo_flag_wires_the_live_fetcher(monkeypatch):
    calls = []
    live = {"current": {"temperature_2m": 1.5, "relative_humidity_2m": 50, "weather_code": 0}}
    monkeypatch.setattr(weather_main.tools, "fetch_open_meteo", lambda: calls.append(1) or live)
    parser = build_parser("seoul-weather", 9101); weather_main._extra_args(parser)
    on = weather_main._build_tools(parser.parse_args(["--open-meteo"]))[0]
    off = weather_main._build_tools(parser.parse_args([]))[0]
    assert on("중구")["source"] == "open-meteo" and calls == [1]
    assert off("중구")["source"] == "dummy" and calls == [1]
