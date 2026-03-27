"""Simple file lock for sync loops."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from leaflink.exceptions import ProjectError

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


@dataclass
class FileLock:
    """An advisory POSIX file lock."""

    path: Path
    _handle: object | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        if fcntl is None:  # pragma: no cover
            self._handle = handle
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ProjectError(
                f"Another leaflink process is already using {self.path.parent.parent}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
