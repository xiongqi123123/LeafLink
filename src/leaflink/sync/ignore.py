"""Ignore pattern handling for .leafignore."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_IGNORE_PATTERNS = [
    ".leaflink/",
    ".git/",
    ".DS_Store",
    "*.aux",
    "*.log",
    "*.synctex.gz",
    "*.synctex(busy)",
    "*.fdb_latexmk",
    "*.fls",
    "*.out",
]


@dataclass(slots=True)
class IgnoreMatcher:
    patterns: list[str]

    @classmethod
    def from_project(cls, project_root: Path, ignore_file: str = ".leafignore") -> "IgnoreMatcher":
        patterns = list(DEFAULT_IGNORE_PATTERNS)
        path = project_root / ignore_file
        if path.exists():
            patterns.extend(_parse_ignore_lines(path.read_text(encoding="utf-8").splitlines()))
        return cls(patterns)

    def matches(self, relative_path: str, is_dir: bool = False) -> bool:
        normalized = relative_path.strip("/")
        candidates = {normalized, f"/{normalized}"}
        if is_dir and normalized:
            candidates |= {f"{normalized}/", f"/{normalized}/"}
        for raw_pattern in self.patterns:
            pattern = raw_pattern.strip()
            if not pattern or pattern.startswith("#"):
                continue
            directory_only = pattern.endswith("/")
            core = pattern.rstrip("/")
            for candidate in candidates:
                if directory_only:
                    if candidate == core or candidate.startswith(f"{core}/") or fnmatch(candidate, f"{core}/*"):
                        return True
                if "/" in core:
                    if fnmatch(candidate, core):
                        return True
                else:
                    parts = [part for part in candidate.split("/") if part]
                    if fnmatch(candidate, core) or any(fnmatch(part, core) for part in parts):
                        return True
        return False


def _parse_ignore_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
