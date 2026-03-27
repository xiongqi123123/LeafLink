"""Data models used by the Overleaf client and sync engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SessionCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = True
    http_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class AuthSession:
    base_url: str
    cookies: list[SessionCookie]
    created_at: str
    updated_at: str

    def cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookies)


@dataclass(slots=True)
class ProjectSummary:
    project_id: str
    name: str
    updated_at: str | None = None


@dataclass(slots=True)
class ProjectInfo:
    project_id: str
    name: str
    base_url: str
    revision: str | None = None


@dataclass(slots=True)
class RemoteEntity:
    entity_id: str
    entity_type: str
    path: str
    name: str
    parent_folder_id: str | None = None


@dataclass(slots=True)
class RemoteProjectTree:
    project_id: str
    root_folder_id: str
    entities: dict[str, RemoteEntity]


@dataclass(slots=True)
class RemoteFile:
    path: str
    content_hash: str
    size: int
    mtime: float = 0.0
    is_binary: bool = False
    updated_at: str | None = None
    updated_by: str | None = None


@dataclass(slots=True)
class RemoteProjectSnapshot:
    project_id: str
    project_name: str
    revision: str | None = None
    files: dict[str, RemoteFile] = field(default_factory=dict)


@dataclass(slots=True)
class DownloadedArchive:
    project_id: str
    project_name: str
    files: dict[str, bytes]


@dataclass(slots=True)
class UploadResult:
    uploaded: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
