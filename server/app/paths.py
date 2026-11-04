from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def dev_dir(self) -> Path:
        return self.data_dir / "dev"

    @property
    def scripts_dir(self) -> Path:
        return self.root / "scripts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "config.db"

    def ensure(self) -> None:
        for d in (self.logs_dir, self.data_dir, self.dev_dir, self.scripts_dir):
            d.mkdir(parents=True, exist_ok=True)
