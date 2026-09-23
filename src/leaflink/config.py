"""Application-level configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from leaflink.utils.paths import app_config_dir

SUPPORTED_BASE_URLS = (
    "https://www.overleaf.com",
    "https://cn.overleaf.com",
)


def normalize_base_url(value: str) -> str:
    """Return a validated HTTP(S) origin for an Overleaf-compatible instance."""

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must be an HTTP or HTTPS URL.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Base URL must include a valid port.") from exc
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not include credentials.")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Base URL must be a bare origin without path, query, or fragment.")
    return f"{parsed.scheme}://{parsed.netloc.lower()}".rstrip("/")


def infer_base_url_from_project_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if not parsed.path.startswith("/project/"):
        return None
    return normalize_base_url(f"{parsed.scheme}://{parsed.netloc}")


@dataclass(slots=True)
class AppConfig:
    """User-level configuration stored in the config directory."""

    default_base_url: str = SUPPORTED_BASE_URLS[0]
    log_level: str = "INFO"

    @classmethod
    def default(cls) -> "AppConfig":
        return cls()


class ConfigStore:
    """Read and write the lightweight TOML config file."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_config_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "config.toml"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig.default()
        raw = _parse_toml_map(self.path.read_text(encoding="utf-8"))
        return AppConfig(
            default_base_url=raw.get("default_base_url", SUPPORTED_BASE_URLS[0]),
            log_level=raw.get("log_level", "INFO"),
        )

    def save(self, config: AppConfig) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        body = (
            f'default_base_url = "{config.default_base_url}"\n'
            f'log_level = "{config.log_level}"\n'
        )
        self.path.write_text(body, encoding="utf-8")


def _parse_toml_map(content: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result
