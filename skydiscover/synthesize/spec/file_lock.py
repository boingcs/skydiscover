"""Cross-platform advisory file locks for SkySynth's small JSON stores."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import BinaryIO, Iterator


@contextmanager
def exclusive_file_lock(file: BinaryIO) -> Iterator[None]:
    """Hold an exclusive advisory lock on the first byte of ``file``.

    POSIX uses ``flock``.  Windows has no ``fcntl`` module, so use the
    corresponding byte-range lock in ``msvcrt``.  Sidecar lock files do not
    carry data; the single marker byte only gives Windows something to lock.
    """

    file.seek(0, os.SEEK_END)
    if file.tell() == 0:
        file.write(b"\0")
        file.flush()
    file.seek(0)

    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)
