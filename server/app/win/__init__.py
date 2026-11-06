"""Windows API adapters. Everything that calls Windows APIs lives behind this package."""

import sys

IS_WINDOWS: bool = sys.platform == "win32"
