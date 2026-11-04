import argparse
from collections.abc import Callable, Sequence

from common.server import run
from seoul_weather import tools


def _extra_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--open-meteo", action="store_true",
                        help="use live Open-Meteo data for get_current_weather (falls back to dummy on any error)")


def _build_tools(args: argparse.Namespace) -> Sequence[Callable]:
    fetch = tools.fetch_open_meteo if args.open_meteo else None

    def get_current_weather(district: str) -> dict:
        """Current weather for one of Seoul's 25 districts (e.g. 강남구)."""
        return tools.get_current_weather(district, fetch=fetch)

    def get_forecast(days: int) -> list[dict]:
        """Daily forecast for Seoul, 1 to 7 days."""
        return tools.get_forecast(days)

    return [get_current_weather, get_forecast]


if __name__ == "__main__":
    run("seoul-weather", _build_tools, None, 9101, extra_args=_extra_args)
