"""Shared exceptions for leaflink."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from leaflink.sync.conflict import MergeAnalysis


class LeafsyncError(Exception):
    """Base error for the project."""


class ConfigError(LeafsyncError):
    """Raised when local configuration is missing or invalid."""


class AuthenticationError(LeafsyncError):
    """Raised when authentication is missing or rejected."""


class ClientError(LeafsyncError):
    """Raised when the remote client fails."""


class BrowserUnavailableError(LeafsyncError):
    """Raised when Playwright or its Chromium build cannot be used."""

    def __init__(self, message: str, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


class ProjectError(LeafsyncError):
    """Raised when project metadata is missing or invalid."""


class SyncConflictError(LeafsyncError):
    """Raised when local and remote edits conflict."""

    def __init__(
        self,
        message: str,
        conflicts: list[str] | None = None,
        details: dict[str, "MergeAnalysis"] | None = None,
    ) -> None:
        super().__init__(message)
        self.conflicts = conflicts or []
        self.details = details or {}
