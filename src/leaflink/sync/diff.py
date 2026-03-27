"""Diff and conflict detection helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from leaflink.sync.state import FileFingerprint


@dataclass(slots=True)
class ChangeSet:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def all_paths(self) -> set[str]:
        return set(self.added) | set(self.modified) | set(self.deleted)

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)


@dataclass(slots=True)
class DiffResult:
    local: ChangeSet
    remote: ChangeSet
    conflicts: list[str]


def diff_files(
    previous: dict[str, FileFingerprint],
    current: dict[str, FileFingerprint],
) -> ChangeSet:
    added = sorted(set(current) - set(previous))
    deleted = sorted(set(previous) - set(current))
    modified = sorted(
        path
        for path in set(previous) & set(current)
        if previous[path].sha256 != current[path].sha256
    )
    return ChangeSet(added=added, modified=modified, deleted=deleted)


def detect_conflicts(local: ChangeSet, remote: ChangeSet) -> list[str]:
    conflicts = local.all_paths() & remote.all_paths()
    return sorted(conflicts)


def detect_divergence(
    local: dict[str, FileFingerprint],
    remote: dict[str, FileFingerprint],
) -> list[str]:
    divergent: list[str] = []
    for path in sorted(set(local) | set(remote)):
        local_item = local.get(path)
        remote_item = remote.get(path)
        if local_item is None or remote_item is None:
            divergent.append(path)
            continue
        if local_item.sha256 != remote_item.sha256:
            divergent.append(path)
    return divergent
