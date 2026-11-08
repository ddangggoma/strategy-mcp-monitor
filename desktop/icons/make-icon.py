# /// script
# requires-python = ">=3.12"
# dependencies = ["resvg-py==0.5.0", "pillow==13.0.0"]
# ///
"""Renders the brand masters (docs/assets/brand/) into the files the app ships.

    uv run desktop/icons/make-icon.py

- desktop/icons/icon.ico: the exe, window, taskbar and tray icon (tauri.conf.json bundle.icon).
  PNG frames; 16-24 px from icon-small.svg, 32-256 px from icon.svg.
- web/public/favicon.svg: icon-small.svg (browser tabs draw it at 16-32 px).
- docs/assets/brand/icon-256.png: a preview for documents that cannot show SVG.
Run it after changing a master; the outputs are committed.
"""

import io
import shutil
from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "docs" / "assets" / "brand"
SMALL = (16, 20, 24)
LARGE = (32, 40, 48, 64, 128, 256)


def render(svg: Path, size: int) -> Image.Image:
    png = bytes(resvg_py.svg_to_bytes(svg_path=str(svg), width=size, height=size))
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    frames = [render(BRAND / "icon-small.svg", s) for s in SMALL]
    frames += [render(BRAND / "icon.svg", s) for s in LARGE]
    largest = frames[-1]
    largest.save(
        ROOT / "desktop" / "icons" / "icon.ico",
        format="ICO",
        sizes=[f.size for f in frames],
        append_images=frames[:-1],
    )
    largest.save(BRAND / "icon-256.png", optimize=True)
    shutil.copyfile(BRAND / "icon-small.svg", ROOT / "web" / "public" / "favicon.svg")


if __name__ == "__main__":
    main()
