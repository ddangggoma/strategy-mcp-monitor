import pytest

pytestmark = pytest.mark.winlive


def test_pywin32_modules_import():
    import pythoncom  # noqa: F401
    import win32com.client  # noqa: F401
    import win32event  # noqa: F401
    import win32evtlog  # noqa: F401
    import win32process  # noqa: F401
    import win32profile  # noqa: F401
    import win32security  # noqa: F401
    import win32ts

    assert win32ts.WTS_CURRENT_SERVER_HANDLE == 0
