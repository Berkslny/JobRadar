"""Cross-process lock so a scheduled run, a CLI run and a run started from the
panel or the Mac app never scan and evaluate at the same time."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows: no cross-process lock, runs are rare enough there
    fcntl = None  # type: ignore[assignment]


def _lock_path(data_path: Path) -> Path:
    data_path.mkdir(parents=True, exist_ok=True)
    return data_path / ".cycle.lock"


@contextmanager
def cycle_lock(data_path: Path) -> Iterator[bool]:
    """Yields True if this process got the lock, False if another run holds it."""
    if fcntl is None:
        yield True
        return
    fd = os.open(_lock_path(data_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def cycle_running(data_path: Path) -> bool:
    if fcntl is None:
        return False
    path = _lock_path(data_path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
