"""Shared safety helpers for repository-local verification tools."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".venv-win",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
}

SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}

SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
}

BINARY_SUFFIXES = {
    ".7z",
    ".avif",
    ".bmp",
    ".class",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".tar",
    ".webp",
    ".zip",
}

RAW_COMMAND_PATTERN = re.compile(
    r"(^|\s)(bash|sh|cmd|powershell|pwsh|python|pip|curl|wget|git|docker)\s+(-|/|[a-zA-Z0-9_.\\/:])",
    re.IGNORECASE,
)
SHELL_META_PATTERN = re.compile(r"(\|\||&&|[|`$<>;])")


class ToolPolicyError(ValueError):
    """Raised when a requested verification plan violates the tool policy."""


def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_safe_relative_path(path: str) -> bool:
    if not path or path.strip() != path:
        return False
    normalized = normalize_repo_path(path)
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    if re.match(r"^[a-zA-Z]:", path):
        return False
    return not contains_shell_syntax(path)


def is_sensitive_path(path: str | Path) -> bool:
    pure = PurePosixPath(normalize_repo_path(str(path)))
    lower_parts = [part.lower() for part in pure.parts]
    name = pure.name.lower()
    if name in SENSITIVE_FILENAMES:
        return True
    if pure.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return any(part in {".ssh", ".aws", ".azure", ".gcp", ".gnupg"} for part in lower_parts)


def should_skip_path(path: str | Path) -> bool:
    pure = PurePosixPath(normalize_repo_path(str(path)))
    lower_parts = {part.lower() for part in pure.parts}
    return bool(lower_parts & SKIP_DIR_NAMES) or is_sensitive_path(str(pure)) or pure.suffix.lower() in BINARY_SUFFIXES


def safe_join(root: Path, relative_path: str) -> Path:
    if not is_safe_relative_path(relative_path) or is_sensitive_path(relative_path):
        raise ToolPolicyError(f"Unsafe repository path: {relative_path!r}")
    root_resolved = root.resolve()
    target = (root_resolved / normalize_repo_path(relative_path)).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ToolPolicyError(f"Path escapes repository root: {relative_path!r}") from exc
    return target


def contains_shell_syntax(value: str) -> bool:
    return bool(SHELL_META_PATTERN.search(value))


def looks_like_raw_command(value: str) -> bool:
    return bool(RAW_COMMAND_PATTERN.search(value.strip())) or contains_shell_syntax(value)


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n...[truncated]", True


def write_json_artifact(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def relative_artifact_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)
