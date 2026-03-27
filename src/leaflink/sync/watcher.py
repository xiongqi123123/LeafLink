"""Filesystem change batching and optional watchdog integration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from leaflink.sync.ignore import IgnoreMatcher

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover
    FileSystemEventHandler = object
    Observer = None


@dataclass(slots=True)
class BatchedLocalChanges:
    changed_paths: set[str] = field(default_factory=set)
    changed_at: dict[str, float] = field(default_factory=dict)
    last_event_at: float | None = None

    def record(self, relative_path: str, timestamp: float | None = None) -> None:
        observed_at = time.monotonic() if timestamp is None else timestamp
        self.changed_paths.add(relative_path)
        self.changed_at[relative_path] = observed_at
        self.last_event_at = observed_at

    def ready(self, debounce_seconds: float, now: float | None = None) -> bool:
        if self.last_event_at is None or not self.changed_paths:
            return False
        current = time.monotonic() if now is None else now
        return current - self.last_event_at >= debounce_seconds

    def pop(self) -> list[str]:
        items = sorted(self.changed_paths)
        self.changed_paths.clear()
        self.changed_at.clear()
        self.last_event_at = None
        return items

    def pop_events(self) -> list[tuple[str, float]]:
        items = [(path, self.changed_at.get(path, self.last_event_at or time.monotonic())) for path in sorted(self.changed_paths)]
        self.changed_paths.clear()
        self.changed_at.clear()
        self.last_event_at = None
        return items


class _EventHandler(FileSystemEventHandler):
    def __init__(self, project_root: Path, ignore: IgnoreMatcher, batch: BatchedLocalChanges) -> None:
        self.project_root = project_root
        self.ignore = ignore
        self.batch = batch

    def on_any_event(self, event) -> None:  # pragma: no cover - covered via batcher tests
        if getattr(event, "is_directory", False):
            return
        src_path = Path(event.src_path)
        try:
            relative = src_path.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError:
            return
        if self.ignore.matches(relative):
            return
        self.batch.record(relative)


class LocalWatcher:
    """Wrap watchdog when available."""

    def __init__(self, project_root: Path, ignore: IgnoreMatcher, batch: BatchedLocalChanges) -> None:
        self.project_root = project_root
        self.ignore = ignore
        self.batch = batch
        self._observer = None

    def start(self) -> None:
        if Observer is None:
            return
        self._observer = Observer()
        self._observer.schedule(_EventHandler(self.project_root, self.ignore, self.batch), str(self.project_root), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
