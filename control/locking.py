"""Interprocess locks shared by HTTP mutations, workers and maintenance helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class FileLock:
    def __init__(self, path: Path, *, blocking: bool = True) -> None:
        self.path, self.blocking = path, blocking
        self.file: BinaryIO | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                if self.path.stat().st_size == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except BaseException:
            self.file.close()
            self.file = None
            raise
        return self

    def __exit__(self, *_: object) -> None:
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
