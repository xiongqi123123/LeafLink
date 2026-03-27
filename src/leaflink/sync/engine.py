"""Core sync engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from leaflink.client.models import DownloadedArchive, RemoteProjectSnapshot
from leaflink.client.overleaf_client import OverleafClientProtocol
from leaflink.exceptions import SyncConflictError
from leaflink.project.metadata import ProjectMetadataStore
from leaflink.sync.conflict import (
    CONFLICT_STRATEGIES,
    ConflictStrategy,
    MergeAnalysis,
    analyze_conflict,
    build_remote_conflict_path,
)
from leaflink.sync.diff import ChangeSet, detect_conflicts, diff_files
from leaflink.sync.ignore import IgnoreMatcher
from leaflink.sync.state import (
    StateStore,
    SyncState,
    mark_pulled,
    mark_pushed,
    remote_snapshot_to_fingerprints,
    scan_local_files,
)
from leaflink.sync.watcher import BatchedLocalChanges, LocalWatcher
from leaflink.utils.locks import FileLock
from leaflink.utils.time import local_time_iso, utc_now_iso


@dataclass(slots=True)
class ChangeDetails:
    path: str
    changed_at: str | None = None
    changed_by: str | None = None


@dataclass(slots=True)
class LocalChangeEvent:
    path: str
    changed_at: str | None = None


@dataclass(slots=True)
class SyncLifecycleEvent:
    stage: str
    message: str
    occurred_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SyncReport:
    local_changes: ChangeSet
    remote_changes: ChangeSet
    conflicts: list[str]
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    local_details: dict[str, ChangeDetails] = field(default_factory=dict)
    remote_details: dict[str, ChangeDetails] = field(default_factory=dict)
    conflict_details: dict[str, MergeAnalysis] = field(default_factory=dict)


class SyncEngine:
    """Compare local and remote snapshots, then apply pull or push operations."""

    def __init__(
        self,
        project_root: Path,
        client: OverleafClientProtocol,
        ignore_file: str = ".leafignore",
    ) -> None:
        self.project_root = project_root.resolve()
        self.metadata = ProjectMetadataStore(self.project_root)
        self.metadata.require_initialized()
        self.project = self.metadata.load_project()
        self.client = client
        self.ignore = IgnoreMatcher.from_project(self.project_root, ignore_file=ignore_file)
        self.state_store = StateStore(self.metadata)

    def status(self) -> SyncReport:
        state = self.state_store.load()
        local_now = scan_local_files(self.project_root, self.ignore)
        remote_snapshot = self.client.get_project_snapshot(self.project.project_id)
        remote_now = remote_snapshot_to_fingerprints(remote_snapshot)
        local_changes = diff_files(state.local_files, local_now)
        remote_changes = diff_files(state.remote_files, remote_now)
        conflicts = sorted(
            set(detect_conflicts(local_changes, remote_changes))
            | set(_detect_persistent_divergence(state.local_files, state.remote_files, local_now, remote_now))
        )
        local_details = {
            path: ChangeDetails(path=path, changed_at=local_time_iso(item.mtime))
            for path, item in local_now.items()
        }
        remote_details = {
            path: ChangeDetails(path=path, changed_at=item.updated_at, changed_by=item.updated_by)
            for path, item in remote_snapshot.files.items()
        }
        return SyncReport(
            local_changes=local_changes,
            remote_changes=remote_changes,
            conflicts=conflicts,
            local_details=local_details,
            remote_details=remote_details,
        )

    def clone_into(self, archive: DownloadedArchive, revision: str | None = None) -> None:
        for relative_path, content in archive.files.items():
            destination = self.project_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        remote_snapshot = self.client.get_project_snapshot(self.project.project_id)
        local_now = scan_local_files(self.project_root, self.ignore)
        remote_now = remote_snapshot_to_fingerprints(remote_snapshot)
        state = SyncState(local_files=local_now, remote_files=remote_now, last_remote_revision=revision)
        self.state_store.save(mark_pulled(state, revision=revision))
        self._write_base_snapshot_from_local()

    def pull(
        self,
        strategy: str | None = None,
        dry_run: bool = False,
        conflict_resolver: Callable[[str, MergeAnalysis], ConflictStrategy] | None = None,
    ) -> SyncReport:
        report = self.status()
        if strategy is not None and strategy not in CONFLICT_STRATEGIES:
            raise SyncConflictError(f"Unsupported conflict strategy: {strategy}")

        archive = self.client.download_project_archive(self.project.project_id)
        report.conflict_details = self._build_conflict_details(report.conflicts, archive.files)
        unresolved = [path for path, analysis in report.conflict_details.items() if not analysis.can_auto_merge]
        if unresolved and strategy is None and conflict_resolver is None:
            raise SyncConflictError(
                "Conflicts detected during pull.",
                unresolved,
                details={path: report.conflict_details[path] for path in unresolved},
            )

        pulled: list[str] = []
        merged: list[str] = []
        if not dry_run:
            pulled, merged, resolved_paths = self._resolve_conflicts(
                report,
                archive.files,
                strategy=strategy,
                conflict_resolver=conflict_resolver,
                preferred="pull",
            )
            remote_file_paths = set(archive.files)
            delete_paths = sorted(
                (set(report.remote_changes.deleted) | {path for path in report.conflicts if path not in remote_file_paths})
                - resolved_paths
            )
            for path in delete_paths:
                local_path = self.project_root / path
                if not local_path.exists():
                    continue
                if path in report.conflicts:
                    if strategy == "keep-local" or strategy == "duplicate-both":
                        continue
                local_path.unlink()
                pulled.append(path)
            apply_paths = sorted(
                (set(report.remote_changes.added) | set(report.remote_changes.modified))
                | ({path for path in report.conflicts if path in remote_file_paths})
            )
            apply_paths = [path for path in apply_paths if path not in resolved_paths]
            for path in apply_paths:
                content = archive.files[path]
                destination = self.project_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if path in report.conflicts:
                    if strategy == "keep-local":
                        continue
                    if strategy == "duplicate-both":
                        conflict_path = self.project_root / build_remote_conflict_path(path)
                        conflict_path.parent.mkdir(parents=True, exist_ok=True)
                        conflict_path.write_bytes(content)
                        pulled.append(build_remote_conflict_path(path))
                        continue
                destination.write_bytes(content)
                pulled.append(path)
            self._refresh_state(after_pull=True)
        report.pulled = pulled
        report.merged = merged
        if not dry_run:
            report.conflicts = []
        return report

    def push(
        self,
        strategy: str | None = None,
        dry_run: bool = False,
        conflict_resolver: Callable[[str, MergeAnalysis], ConflictStrategy] | None = None,
    ) -> SyncReport:
        report = self.status()
        if strategy is not None and strategy not in CONFLICT_STRATEGIES:
            raise SyncConflictError(f"Unsupported conflict strategy: {strategy}")

        archive = self.client.download_project_archive(self.project.project_id)
        report.conflict_details = self._build_conflict_details(report.conflicts, archive.files)
        unresolved = [path for path, analysis in report.conflict_details.items() if not analysis.can_auto_merge]
        if unresolved and strategy is None and conflict_resolver is None:
            raise SyncConflictError(
                "Conflicts detected during push.",
                unresolved,
                details={path: report.conflict_details[path] for path in unresolved},
            )

        pushed: list[str] = []
        merged: list[str] = []
        if not dry_run:
            pushed, merged, resolved_paths = self._resolve_conflicts(
                report,
                archive.files,
                strategy=strategy,
                conflict_resolver=conflict_resolver,
                preferred="push",
            )
            remote_paths = set(archive.files)
            delete_paths = sorted(
                (set(report.local_changes.deleted) | {path for path in report.conflicts if path not in scan_local_files(self.project_root, self.ignore) and path in remote_paths})
                - resolved_paths
            )
            for path in delete_paths:
                if path in report.conflicts and strategy == "keep-remote":
                    continue
                self.client.delete_file(self.project.project_id, path)
                pushed.append(path)
            upload_paths = sorted(
                (set(report.local_changes.added) | set(report.local_changes.modified))
                | ({path for path in report.conflicts if (self.project_root / path).exists()})
            )
            upload_paths = [path for path in upload_paths if path not in resolved_paths]
            for path in upload_paths:
                if path in report.conflicts and strategy == "keep-remote":
                    continue
                local_path = self.project_root / path
                self.client.upload_file(self.project.project_id, path, local_path.read_bytes())
                pushed.append(path)
            self._refresh_state(after_push=True)
        report.pushed = pushed
        report.merged = merged
        if not dry_run:
            report.conflicts = []
        return report

    def download_pdf(self, output: Path | None = None) -> Path:
        payload = self.client.download_pdf(self.project.project_id)
        destination = output or (self.project_root / f"{self.project.project_name}.pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination

    def sync_once(
        self,
        strategy: str | None = None,
        dry_run: bool = False,
        conflict_resolver: Callable[[str, MergeAnalysis], ConflictStrategy] | None = None,
    ) -> SyncReport:
        pull_report = self.pull(strategy=strategy, dry_run=dry_run, conflict_resolver=conflict_resolver)
        push_report = self.push(strategy=strategy, dry_run=dry_run, conflict_resolver=conflict_resolver)
        return SyncReport(
            local_changes=push_report.local_changes,
            remote_changes=pull_report.remote_changes,
            conflicts=sorted(set(pull_report.conflicts) | set(push_report.conflicts)),
            pushed=push_report.pushed,
            pulled=pull_report.pulled,
            merged=sorted(set(pull_report.merged) | set(push_report.merged)),
            local_details=push_report.local_details,
            remote_details=pull_report.remote_details,
            conflict_details={**pull_report.conflict_details, **push_report.conflict_details},
        )

    def run_sync_loop(
        self,
        interval: float = 10.0,
        debounce: float = 1.5,
        strategy: str | None = None,
        dry_run: bool = False,
        once: bool = False,
        on_event: Callable[[object], None] | None = None,
        conflict_resolver: Callable[[str, MergeAnalysis], ConflictStrategy] | None = None,
    ) -> None:
        lock = FileLock(self.metadata.lock_path)
        batch = BatchedLocalChanges()
        watcher = LocalWatcher(self.project_root, self.ignore, batch)
        with lock:
            if on_event:
                on_event(
                    SyncLifecycleEvent(
                        stage="lock",
                        message=f"Project lock acquired for {self.project.project_name}.",
                    )
                )
            if once:
                if on_event:
                    on_event(SyncLifecycleEvent(stage="startup", message="Running one sync cycle."))
                report = self.sync_once(strategy=strategy, dry_run=dry_run, conflict_resolver=conflict_resolver)
                if on_event:
                    on_event(report)
                return

            if on_event:
                on_event(SyncLifecycleEvent(stage="startup", message="Starting local watcher."))
            watcher.start()
            try:
                if on_event:
                    on_event(
                        SyncLifecycleEvent(
                            stage="ready",
                            message=(
                                f"Sync service started. Watching {self.project_root} "
                                f"(remote poll: {interval:.1f}s, debounce: {debounce:.1f}s)."
                            ),
                        )
                    )
                last_remote_check = 0.0
                while True:
                    now = time.monotonic()
                    local_ready = batch.ready(debounce, now=now)
                    remote_due = now - last_remote_check >= interval
                    if not local_ready and not remote_due:
                        time.sleep(0.2)
                        continue

                    changed: list[tuple[str, float]] = []
                    if local_ready:
                        changed = batch.pop_events()
                        if on_event:
                            on_event(
                                SyncLifecycleEvent(
                                    stage="push",
                                    message=f"Processing {len(changed)} local change(s).",
                                )
                            )
                            for path, observed_at in changed:
                                local_path = self.project_root / path
                                changed_at = local_time_iso(local_path.stat().st_mtime) if local_path.exists() else local_time_iso(observed_at)
                                on_event(LocalChangeEvent(path=path, changed_at=changed_at))

                    if remote_due and on_event:
                        on_event(SyncLifecycleEvent(stage="poll", message="Checking remote changes."))

                    preflight = self.status()
                    if preflight.conflicts:
                        if on_event:
                            on_event(preflight)
                        report = self.sync_once(
                            strategy=strategy,
                            dry_run=dry_run,
                            conflict_resolver=conflict_resolver,
                        )
                        if on_event:
                            on_event(report)
                        last_remote_check = now
                        time.sleep(0.2)
                        continue

                    if remote_due:
                        report = self.pull(strategy=strategy, dry_run=dry_run, conflict_resolver=conflict_resolver)
                        if on_event:
                            on_event(report)
                            if (
                                not report.remote_changes.added
                                and not report.remote_changes.modified
                                and not report.remote_changes.deleted
                                and not report.pulled
                                and not report.conflicts
                            ):
                                on_event(
                                    SyncLifecycleEvent(
                                        stage="poll",
                                        message="Remote unchanged.",
                                    )
                                )
                        last_remote_check = now

                    if local_ready:
                        report = self.push(strategy=strategy, dry_run=dry_run, conflict_resolver=conflict_resolver)
                        if on_event:
                            on_event(report)
                            if not report.pushed and not report.conflicts:
                                on_event(
                                    SyncLifecycleEvent(
                                        stage="push",
                                        message="No uploads needed after local scan.",
                                    )
                                )
                    time.sleep(0.2)
            finally:
                watcher.stop()

    def _refresh_state(self, after_pull: bool = False, after_push: bool = False) -> None:
        remote_snapshot = self.client.get_project_snapshot(self.project.project_id)
        local_now = scan_local_files(self.project_root, self.ignore)
        remote_now = remote_snapshot_to_fingerprints(remote_snapshot)
        state = self.state_store.load()
        state.local_files = local_now
        state.remote_files = remote_now
        state.last_remote_revision = remote_snapshot.revision
        if after_pull:
            mark_pulled(state, revision=remote_snapshot.revision)
        if after_push:
            mark_pushed(state)
        self.state_store.save(state)
        self._write_base_snapshot_from_local()

    def _base_snapshot_root(self) -> Path:
        return self.metadata.cache_dir / "base"

    def _base_snapshot_path(self, relative_path: str) -> Path:
        return self._base_snapshot_root() / Path(relative_path)

    def _read_base_content(self, relative_path: str) -> bytes | None:
        path = self._base_snapshot_path(relative_path)
        if not path.exists():
            return None
        return path.read_bytes()

    def _write_base_snapshot_from_local(self) -> None:
        base_root = self._base_snapshot_root()
        base_root.mkdir(parents=True, exist_ok=True)
        current_paths = scan_local_files(self.project_root, self.ignore)
        existing_paths = [path for path in base_root.rglob("*") if path.is_file()]
        valid_relative_paths = {path for path in current_paths}
        for existing in existing_paths:
            relative = existing.relative_to(base_root).as_posix()
            if relative not in valid_relative_paths:
                existing.unlink()
        for relative_path in valid_relative_paths:
            destination = self._base_snapshot_path(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.project_root / relative_path).read_bytes())

    def _build_conflict_details(self, paths: list[str], remote_files: dict[str, bytes]) -> dict[str, MergeAnalysis]:
        analyses: dict[str, MergeAnalysis] = {}
        for path in paths:
            local_path = self.project_root / path
            local_content = local_path.read_bytes() if local_path.exists() else None
            remote_content = remote_files.get(path)
            base_content = self._read_base_content(path)
            analyses[path] = analyze_conflict(path, base_content, local_content, remote_content)
        return analyses

    def _resolve_conflicts(
        self,
        report: SyncReport,
        remote_files: dict[str, bytes],
        strategy: str | None,
        conflict_resolver: Callable[[str, MergeAnalysis], ConflictStrategy] | None,
        preferred: str,
    ) -> tuple[list[str], list[str], set[str]]:
        changed: list[str] = []
        merged: list[str] = []
        resolved_paths: set[str] = set()
        for path in list(report.conflicts):
            analysis = report.conflict_details.get(path)
            if analysis is None:
                continue
            if analysis.can_auto_merge and analysis.merged_content is not None:
                destination = self.project_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(analysis.merged_content)
                self.client.upload_file(self.project.project_id, path, analysis.merged_content)
                changed.append(path)
                merged.append(path)
                resolved_paths.add(path)
                continue

            chosen = strategy
            if chosen is None and conflict_resolver is not None:
                chosen = conflict_resolver(path, analysis)
            if chosen is None:
                continue

            local_path = self.project_root / path
            remote_content = remote_files.get(path)
            if chosen == "keep-remote":
                if remote_content is None:
                    if local_path.exists():
                        local_path.unlink()
                else:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(remote_content)
                changed.append(path)
                resolved_paths.add(path)
            elif chosen == "keep-local":
                if local_path.exists():
                    self.client.upload_file(self.project.project_id, path, local_path.read_bytes())
                else:
                    self.client.delete_file(self.project.project_id, path)
                changed.append(path)
                resolved_paths.add(path)
            elif chosen == "duplicate-both":
                if remote_content is not None:
                    conflict_path = self.project_root / build_remote_conflict_path(path)
                    conflict_path.parent.mkdir(parents=True, exist_ok=True)
                    conflict_path.write_bytes(remote_content)
                    changed.append(build_remote_conflict_path(path))
                resolved_paths.add(path)
            report.conflicts.remove(path)
        return changed, merged, resolved_paths


def _detect_persistent_divergence(
    previous_local: dict[str, object],
    previous_remote: dict[str, object],
    current_local: dict[str, object],
    current_remote: dict[str, object],
) -> list[str]:
    divergent: list[str] = []
    for path in sorted(set(current_local) | set(current_remote)):
        local_item = current_local.get(path)
        remote_item = current_remote.get(path)
        if local_item is None or remote_item is None:
            if _baseline_differs(previous_local.get(path), previous_remote.get(path)):
                divergent.append(path)
            continue
        if local_item.sha256 != remote_item.sha256 and _baseline_differs(previous_local.get(path), previous_remote.get(path)):
            divergent.append(path)
    return divergent


def _baseline_differs(local_item: object | None, remote_item: object | None) -> bool:
    if local_item is None or remote_item is None:
        return local_item is not remote_item
    return getattr(local_item, "sha256", None) != getattr(remote_item, "sha256", None)
