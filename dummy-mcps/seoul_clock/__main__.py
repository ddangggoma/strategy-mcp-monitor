from common.server import run
from seoul_clock import tools


def now_kst() -> str:
    """Current time in Seoul (KST, ISO-8601 with +09:00)."""
    return tools.now_kst()


def convert_timezone(time: str, tz: str) -> str:
    """Convert an ISO-8601 time (no offset means KST) to an IANA zone name or a +HH:MM offset."""
    return tools.convert_timezone(time, tz)


if __name__ == "__main__":
    run("seoul-clock", [now_kst, convert_timezone], None, 9103)
