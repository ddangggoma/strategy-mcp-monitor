# PyInstaller spec: the session agent (no console window; started in each user session).
# Built by install/build.ps1 from server/: python -m PyInstaller ..\install\pyinstaller\mcp-agent.spec
# Output: <bundle>\bin\agent\mcp-agent.exe (onedir, W26).
from pathlib import Path

HERE = Path(SPECPATH)  # noqa: F821 - defined by PyInstaller
REPO = HERE.parents[1]

a = Analysis(  # noqa: F821
    [str(HERE / "entry_agent.py")],
    pathex=[str(REPO / "agent")],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mcp-agent",
    console=False,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="agent",
)
