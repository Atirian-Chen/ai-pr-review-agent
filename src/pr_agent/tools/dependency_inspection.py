"""Inspect repository dependency manifests without executing installers."""

from __future__ import annotations

import re
import time
from pathlib import Path

from pr_agent.review.schema import ToolKind, ToolResult
from pr_agent.tools.base import should_skip_path, truncate_text, write_json_artifact


MANIFESTS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "Pipfile",
    "package.json",
)
TOOLS = ("pytest", "ruff", "mypy")


def inspect_dependencies(repo_root: Path, artifact_dir: Path | None = None) -> ToolResult:
    started = time.perf_counter()
    discovered: dict[str, list[str]] = {tool: [] for tool in TOOLS}
    manifests: list[str] = []

    for manifest in MANIFESTS:
        path = repo_root / manifest
        if not path.is_file() or should_skip_path(manifest):
            continue
        manifests.append(manifest)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for tool in TOOLS:
            if re.search(rf"(^|[^a-zA-Z0-9_-]){re.escape(tool)}([^a-zA-Z0-9_-]|$)", text, re.IGNORECASE):
                discovered[tool].append(manifest)

    artifact_path = None
    if artifact_dir is not None:
        manifest_previews = {}
        for manifest in manifests:
            content = (repo_root / manifest).read_text(encoding="utf-8", errors="replace")
            manifest_previews[manifest] = truncate_text(content, 4000)[0]
        artifact_path = write_json_artifact(
            artifact_dir / "dependency_inspection.json",
            {
                "manifests": manifests,
                "tools": discovered,
                "manifest_previews": manifest_previews,
            },
        )

    present = sorted(tool for tool, paths in discovered.items() if paths)
    if present:
        summary = f"Detected verification dependencies: {', '.join(present)}."
    elif manifests:
        summary = f"Inspected {len(manifests)} manifest(s), but pytest/ruff/mypy were not declared."
    else:
        summary = "No supported dependency manifest was found."
    return ToolResult(
        tool=ToolKind.DEPENDENCY_INSPECTION,
        success=True,
        summary=summary,
        duration_ms=_duration_ms(started),
        artifact_path=artifact_path,
        matched_paths=manifests,
    )


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
