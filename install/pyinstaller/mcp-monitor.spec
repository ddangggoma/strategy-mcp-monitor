# PyInstaller spec: the monitor server (console; also the Windows service host via `service`).
# Built by install/build.ps1 from server/: python -m PyInstaller ..\install\pyinstaller\mcp-monitor.spec
# Output: <payload>\bin\monitor\mcp-monitor-server.exe (onedir, W26/W27; renamed in Plan 6, Y6, so that
# mcp-monitor.exe is only the desktop app that embeds the payload).
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)  # noqa: F821 - defined by PyInstaller
REPO = HERE.parents[1]

# watchfiles is excluded (no reload), so its uvicorn supervisor is left out too (preflight F24).
uvicorn_modules = collect_submodules("uvicorn", filter=lambda name: "watchfilesreload" not in name)

a = Analysis(  # noqa: F821
    [str(HERE / "entry_monitor.py")],
    pathex=[str(REPO / "server")],
    hiddenimports=uvicorn_modules + [
        "httptools",
        "websockets",
        "app.winsvc.service",
        "win32timezone",
        "win32serviceutil",
        "servicemanager",
    ],
    excludes=["watchfiles", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mcp-monitor-server",
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="monitor",
)
