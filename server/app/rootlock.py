"""One MCP Monitor process per data root (W24): an exclusive byte lock on ``data/.lock``."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

from app.paths import AppPaths


class RootInUseError(RuntimeError):
    """Another process (a server, the service or ``reindex``) holds the data root."""

    def __init__(self, root: Path) -> None:
        super().__init__(f"data root {root} is already in use by another MCP Monitor process")
        self.root = root


class RootLock:
    """``acquire()`` locks the first byte of ``<root>/data/.lock`` without waiting; the lock goes
    away with the handle, so a crashed process never leaves the root locked."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = AppPaths(self.root).data_dir / ".lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            raise RuntimeError("root lock already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _lock(fd)
        except OSError:
            os.close(fd)
            raise RootInUseError(self.root) from None
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        except OSError:
            pass  # closing the handle releases the lock anyway
        finally:
            os.close(fd)

    def __enter__(self) -> RootLock:
        self.acquire()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - the product runs on Windows only
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
