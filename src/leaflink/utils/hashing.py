"""Hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(content: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(content)
    return digest.hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
