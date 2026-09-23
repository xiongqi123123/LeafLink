"""Ignore pattern handling for .leafignore."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
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

    @classmethod
    def from_text(cls, text: str) -> "IgnoreMatcher":
        return cls([*DEFAULT_IGNORE_PATTERNS, *_parse_ignore_lines(text.splitlines())])

    def matches(self, relative_path: str, is_dir: bool = False) -> bool:
        parts = tuple(relative_path.strip("/").split("/"))
        # Metadata must never be transferred, even with a negation rule.
        if any(part in {".git", ".leaflink"} for part in parts):
            return True
        ignored = False
        for raw_pattern in self.patterns:
            pattern = raw_pattern.strip()
            if not pattern or pattern.startswith("#"):
                continue
            negate = pattern.startswith("!")
            if negate:
                pattern = pattern[1:]
            if not pattern:
                continue
            directory_only = pattern.endswith("/")
            anchored = pattern.startswith("/")
            core = pattern.strip("/")
            if not core:
                continue
            # Test the path and its directory ancestors. A directory rule does
            # not match a regular file with the same name.
            for end in range(1, len(parts) + 1):
                if directory_only and end == len(parts) and not is_dir:
                    continue
                candidate = parts[:end]
                matched = (
                    _match_path(candidate, tuple(core.split("/")))
                    if anchored or "/" in core
                    else fnmatchcase(candidate[-1], core)
                )
                if matched:
                    ignored = not negate
                    break
        return ignored


def _match_path(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return _match_path(parts, pattern[1:]) or bool(parts and _match_path(parts[1:], pattern))
    return bool(parts and fnmatchcase(parts[0], pattern[0]) and _match_path(parts[1:], pattern[1:]))


def _parse_ignore_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
