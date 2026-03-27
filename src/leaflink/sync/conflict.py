"""Conflict resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from merge3 import Merge3


CONFLICT_STRATEGIES = ("keep-local", "keep-remote", "duplicate-both")
ConflictStrategy = Literal["keep-local", "keep-remote", "duplicate-both"]


@dataclass(slots=True)
class ConflictDecision:
    strategy: ConflictStrategy
    paths: list[str]


def build_remote_conflict_path(relative_path: str) -> str:
    path = Path(relative_path)
    suffix = "".join(path.suffixes)
    stem = path.name[: -len(suffix)] if suffix else path.name
    new_name = f"{stem}.remote.conflict{suffix}"
    return path.with_name(new_name).as_posix()


@dataclass(slots=True)
class MergeAnalysis:
    path: str
    can_auto_merge: bool
    merged_content: bytes | None = None
    preview: str | None = None
    reason: str | None = None
    is_binary: bool = False


def analyze_conflict(
    path: str,
    base_content: bytes | None,
    local_content: bytes | None,
    remote_content: bytes | None,
) -> MergeAnalysis:
    if local_content == remote_content:
        return MergeAnalysis(path=path, can_auto_merge=True, merged_content=local_content or remote_content or b"")

    if local_content is None or remote_content is None:
        return MergeAnalysis(
            path=path,
            can_auto_merge=False,
            preview=_build_binary_preview(path, local_content, remote_content),
            reason="One side deleted the file while the other side kept content.",
            is_binary=True,
        )

    if _looks_binary(local_content) or _looks_binary(remote_content) or (base_content is not None and _looks_binary(base_content)):
        return MergeAnalysis(
            path=path,
            can_auto_merge=False,
            preview=_build_binary_preview(path, local_content, remote_content),
            reason="Binary files cannot be merged automatically.",
            is_binary=True,
        )

    local_text = local_content.decode("utf-8", errors="replace")
    remote_text = remote_content.decode("utf-8", errors="replace")
    if base_content is None or _looks_binary(base_content):
        return MergeAnalysis(
            path=path,
            can_auto_merge=False,
            preview=build_conflict_preview(path, local_text, remote_text),
            reason="No common sync base is available for a safe three-way merge.",
        )

    base_text = base_content.decode("utf-8", errors="replace")
    merged = try_three_way_merge(path, base_text, local_text, remote_text)
    if merged is not None:
        return MergeAnalysis(path=path, can_auto_merge=True, merged_content=merged.encode("utf-8"))
    return MergeAnalysis(
        path=path,
        can_auto_merge=False,
        preview=build_merge3_conflict_preview(path, base_text, local_text, remote_text),
        reason="Local and remote edits overlap in the same text region.",
    )


def try_three_way_merge(path: str, base_text: str, local_text: str, remote_text: str) -> str | None:
    if local_text == remote_text:
        return local_text
    if local_text == base_text:
        return remote_text
    if remote_text == base_text:
        return local_text

    merge3 = Merge3(
        base_text.splitlines(keepends=True),
        local_text.splitlines(keepends=True),
        remote_text.splitlines(keepends=True),
    )
    regions = list(merge3.merge_regions())
    if any(region[0] == "conflict" for region in regions):
        return None
    return "".join(
        merge3.merge_lines(
            name_a=f"local/{path}",
            name_b=f"remote/{path}",
            name_base=f"base/{path}",
            base_marker="|||||||",
        )
    )


def build_conflict_preview(path: str, local_text: str, remote_text: str, context_lines: int = 3, max_lines: int = 80) -> str:
    from difflib import unified_diff

    diff_lines = list(
        unified_diff(
            remote_text.splitlines(),
            local_text.splitlines(),
            fromfile=f"remote/{path}",
            tofile=f"local/{path}",
            lineterm="",
            n=context_lines,
        )
    )
    if not diff_lines:
        return f"Conflict in {path}, but no textual diff preview is available."
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines] + ["... (diff truncated)"]
    return "\n".join(diff_lines)


def build_merge3_conflict_preview(
    path: str,
    base_text: str,
    local_text: str,
    remote_text: str,
    max_lines: int = 80,
) -> str:
    merge3 = Merge3(
        base_text.splitlines(keepends=True),
        local_text.splitlines(keepends=True),
        remote_text.splitlines(keepends=True),
    )
    lines = list(
        merge3.merge_lines(
            name_a=f"local/{path}",
            name_b=f"remote/{path}",
            name_base=f"base/{path}",
            base_marker="|||||||",
        )
    )
    preview_lines = [line.rstrip("\n") for line in lines]
    if len(preview_lines) > max_lines:
        preview_lines = preview_lines[:max_lines] + ["... (conflict preview truncated)"]
    return "\n".join(preview_lines)


def _build_binary_preview(path: str, local_content: bytes | None, remote_content: bytes | None) -> str:
    local_size = len(local_content) if local_content is not None else 0
    remote_size = len(remote_content) if remote_content is not None else 0
    return (
        f"Binary conflict for {path}\n"
        f"  local:  {'missing' if local_content is None else f'{local_size} bytes'}\n"
        f"  remote: {'missing' if remote_content is None else f'{remote_size} bytes'}"
    )


def _looks_binary(payload: bytes) -> bool:
    return b"\0" in payload
