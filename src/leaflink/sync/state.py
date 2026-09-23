"""State snapshots for local and remote files."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from leaflink.client.models import RemoteProjectSnapshot
from leaflink.project.metadata import ProjectMetadataStore
from leaflink.sync.ignore import IgnoreMatcher
from leaflink.utils.hashing import sha256_bytes, sha256_file
from leaflink.utils.time import utc_now_iso


@dataclass(slots=True)
class FileFingerprint:
    path: str
    size: int
    mtime: float
    sha256: str


@dataclass(slots=True)
class SyncState:
    local_files: dict[str, FileFingerprint] = field(default_factory=dict)
    remote_files: dict[str, FileFingerprint] = field(default_factory=dict)
    last_pull_at: str | None = None
    last_push_at: str | None = None
    last_remote_revision: str | None = None


class StateStore:
    """Persist sync state in .leaflink/state.json."""

    def __init__(self, metadata: ProjectMetadataStore) -> None:
        self.metadata = metadata

    def load(self) -> SyncState:
        if not self.metadata.state_path.exists():
            return SyncState()
        raw = json.loads(self.metadata.state_path.read_text(encoding="utf-8"))
        return SyncState(
            local_files={
                path: FileFingerprint(**fingerprint)
                for path, fingerprint in raw.get("local_files", {}).items()
            },
            remote_files={
                path: FileFingerprint(**fingerprint)
                for path, fingerprint in raw.get("remote_files", {}).items()
            },
            last_pull_at=raw.get("last_pull_at"),
            last_push_at=raw.get("last_push_at"),
            last_remote_revision=raw.get("last_remote_revision"),
        )

    def save(self, state: SyncState) -> None:
        self.metadata.meta_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "local_files": {path: asdict(item) for path, item in state.local_files.items()},
            "remote_files": {path: asdict(item) for path, item in state.remote_files.items()},
            "last_pull_at": state.last_pull_at,
            "last_push_at": state.last_push_at,
            "last_remote_revision": state.last_remote_revision,
        }
        self.metadata.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


# Cache is scoped to one engine, not persisted as a synchronization baseline.
HashCache = dict[str, tuple[tuple[int, ...], str]]


def scan_local_files(
    project_root: Path, ignore: IgnoreMatcher, *,
    cache: HashCache | None = None, force_hash: bool = False,
) -> dict[str, FileFingerprint]:
    files: dict[str, FileFingerprint] = {}
    seen: set[str] = set()
    for directory, dirs, names in os.walk(project_root):
        # Only prune unconditional metadata exclusions; user rules can reinclude children.
        dirs[:] = sorted(name for name in dirs if name not in {'.git', '.leaflink'})
        for name in sorted(names):
            path = Path(directory) / name
            rel_path = path.relative_to(project_root).as_posix()
            if ignore.matches(rel_path):
                continue
            stat = path.stat()
            signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            previous = cache.get(rel_path) if cache is not None else None
            if not force_hash and previous is not None and previous[0] == signature:
                digest = previous[1]
            else:
                digest = sha256_file(path)
                after = path.stat()
                after_signature = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                # Never reuse a hash if the file changed while it was being read.
                if cache is not None:
                    cache.pop(rel_path, None)
                    if signature == after_signature:
                        cache[rel_path] = (signature, digest)
            seen.add(rel_path)
            files[rel_path] = FileFingerprint(
                path=rel_path, size=stat.st_size, mtime=stat.st_mtime, sha256=digest,
            )
    if cache is not None:
        for removed in cache.keys() - seen:
            del cache[removed]
    return files


def remote_snapshot_to_fingerprints(snapshot: RemoteProjectSnapshot) -> dict[str, FileFingerprint]:
    return {
        path: FileFingerprint(
            path=path,
            size=item.size,
            mtime=item.mtime,
            sha256=item.content_hash,
        )
        for path, item in snapshot.files.items()
    }


def fingerprint_bytes(path: str, content: bytes) -> FileFingerprint:
    return FileFingerprint(path=path, size=len(content), mtime=0.0, sha256=sha256_bytes(content))


def mark_pulled(state: SyncState, revision: str | None = None) -> SyncState:
    state.last_pull_at = utc_now_iso()
    state.last_remote_revision = revision
    return state


def mark_pushed(state: SyncState) -> SyncState:
    state.last_push_at = utc_now_iso()
    return state
