"""Application-level configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from leaflink.utils.paths import app_config_dir

SUPPORTED_BASE_URLS = (
    "https://www.overleaf.com",
    "https://cn.overleaf.com",
)


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
