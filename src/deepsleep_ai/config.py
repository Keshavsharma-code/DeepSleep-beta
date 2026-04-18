from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryConfig(BaseSettings):
    max_bytes: int = 8192  # 8KB — enough to hold rich session context without aggressive loss
    compression_level: str = "conservative"  # conservative | aggressive | strict


class WatchConfig(BaseSettings):
    idle_seconds: int = 300
    poll_interval: float = 1.0
    snapshot_window: int = 1800
    respect_gitignore: bool = True
    max_file_size_mb: int = 5


class LLMConfig(BaseSettings):
    default_model: str = "deepseek-r1"
    timeout: int = 120
    max_context_files: int = 5  # was 3 — allows richer file context per query
    fallback_on_timeout: bool = True


class PrivacyConfig(BaseSettings):
    encrypt_memory: bool = False
    exclude_patterns: List[str] = [".env*", "*secret*", "*.key"]


class DeepSleepConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEEPSLEEP_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    memory: MemoryConfig = MemoryConfig()
    watch: WatchConfig = WatchConfig()
    llm: LLMConfig = LLMConfig()
    privacy: PrivacyConfig = PrivacyConfig()

    @classmethod
    def load_from_project(cls, project_root: Path) -> DeepSleepConfig:
        """Load config from .deepsleep/config.toml if it exists."""
        # Note: In a real implementation with tomllib, we'd merge the TOML data.
        # For simplicity in this v1.0 upgrade, we'll return defaults or env overrides.
        config_path = project_root / ".deepsleep" / "config.toml"
        if config_path.exists():
            try:
                import tomllib
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
                    return cls(**data)
            except Exception:
                pass
        return cls()
