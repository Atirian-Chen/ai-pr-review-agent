"""配置加载模块：把 YAML 配置转换为强类型对象，供 CLI 和各子模块共享。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewSettings(BaseModel):
    max_files: int = 20
    max_findings: int = 8
    confidence_threshold: float = 0.6
    temperature: float = 0.1
    reviewer_mode: Literal["single", "multi_agent"] = "multi_agent"
    enabled_reviewers: list[str] = Field(default_factory=lambda: ["bug", "test", "security", "performance"])


class FilterSettings(BaseModel):
    skip_paths: list[str] = Field(default_factory=lambda: ["dist/", "build/", "node_modules/"])
    skip_files: list[str] = Field(
        default_factory=lambda: ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"]
    )
    skip_extensions: list[str] = Field(
        default_factory=lambda: [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock", ".zip", ".exe"]
    )
    max_patch_lines_per_file: int = 800


class ContextSettings(BaseModel):
    surrounding_lines: int = 30
    include_readme: bool = True
    include_related_tests: bool = True
    max_context_chars_per_file: int = 12000
    readme_excerpt_chars: int = 2000


class LLMSettings(BaseModel):
    provider: str = "openai_compatible"
    model: str = "gpt-4.1-mini"
    temperature: float = 0.1
    max_output_tokens: int = 3000
    timeout_seconds: float = 120.0


class VerifierLLMSettings(LLMSettings):
    enabled: bool = True
    model: str = "gpt-4.1-mini"
    temperature: float = 0.0
    max_output_tokens: int = 2000
    timeout_seconds: float = 60.0


class GitHubSettings(BaseModel):
    api_base_url: str = "https://api.github.com"
    timeout_seconds: float = 30.0


class AppConfig(BaseModel):
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    verifier_llm: VerifierLLMSettings = Field(default_factory=VerifierLLMSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置，避免用户只改一个字段时覆盖整个分组。"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> AppConfig:
    default_path = Path.cwd() / "configs" / "default.yml"
    candidate = Path(path) if path else default_path

    data: dict[str, Any] = {}
    if candidate.exists():
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required to load YAML config files") from exc
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file must contain a YAML mapping: {candidate}")
        data = loaded

    return AppConfig.model_validate(_deep_merge(AppConfig().model_dump(), data))
