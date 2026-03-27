"""State snapshots for local and remote files."""

from __future__ import annotations

import json
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


def scan_local_files(project_root: Path, ignore: IgnoreMatcher) -> dict[str, FileFingerprint]:
    files: dict[str, FileFingerprint] = {}
    for path in sorted(project_root.rglob("*")):
        rel_path = path.relative_to(project_root).as_posix()
        if path.is_dir():
            if ignore.matches(rel_path, is_dir=True):
                continue
            continue
        if ignore.matches(rel_path):
            continue
        stat = path.stat()
        files[rel_path] = FileFingerprint(
            path=rel_path,
            size=stat.st_size,
            mtime=stat.st_mtime,
            sha256=sha256_file(path),
        )
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
