"""Read and write project-local metadata inside .leaflink/."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from leaflink.exceptions import ProjectError
from leaflink.utils.paths import ensure_dir


@dataclass(slots=True)
class ProjectConfig:
    project_id: str
    base_url: str
    project_name: str
    last_known_remote_revision: str | None = None


class ProjectMetadataStore:
    """Manage the .leaflink directory for a cloned project."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.meta_dir = self.project_root / ".leaflink"
        self.project_path = self.meta_dir / "project.json"
        self.state_path = self.meta_dir / "state.json"
        self.lock_path = self.meta_dir / "lock"
        self.cache_dir = self.meta_dir / "cache"
        self.logs_dir = self.meta_dir / "logs"

    def init(self, config: ProjectConfig) -> None:
        ensure_dir(self.meta_dir)
        ensure_dir(self.cache_dir)
        ensure_dir(self.logs_dir)
        self.save_project(config)

    def require_initialized(self) -> None:
        if not self.project_path.exists():
            raise ProjectError(
                f"{self.project_root} is not a leaflink project. Run `leaflink clone` first."
            )

    def load_project(self) -> ProjectConfig:
        self.require_initialized()
        raw = json.loads(self.project_path.read_text(encoding="utf-8"))
        return ProjectConfig(**raw)

    def save_project(self, config: ProjectConfig) -> None:
        ensure_dir(self.meta_dir)
        self.project_path.write_text(
            json.dumps(asdict(config), indent=2, sort_keys=True),
            encoding="utf-8",
        )
