"""Constrained read-file helper for verification evidence."""

from __future__ import annotations

import time
from pathlib import Path

from pr_agent.review.schema import ToolKind, ToolResult
from pr_agent.tools.base import ToolPolicyError, safe_join, should_skip_path, truncate_text, write_json_artifact


DEFAULT_MAX_CHARS = 6000


def read_repository_file(
    repo_root: Path,
    relative_path: str,
    artifact_dir: Path | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResult:
    started = time.perf_counter()
    try:
        path = safe_join(repo_root, relative_path)
    except ToolPolicyError as exc:
        return _result(started, False, str(exc))

    normalized = path.relative_to(repo_root.resolve()).as_posix()
    if should_skip_path(normalized):
        return _result(started, False, f"Refused to read skipped or sensitive path: {normalized}.")
    if not path.exists() or not path.is_file():
        return _result(started, False, f"File does not exist: {normalized}.")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _result(started, False, f"Could not read {normalized}: {exc.__class__.__name__}.")

    content, truncated = truncate_text(text, max_chars)
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_json_artifact(
            artifact_dir / "read_file.json",
            {
                "path": normalized,
                "content": content,
                "truncated": truncated,
            },
        )
    return ToolResult(
        tool=ToolKind.READ_FILE,
        success=True,
        summary=f"Read {normalized} ({len(text.splitlines())} line(s)).",
        duration_ms=_duration_ms(started),
        artifact_path=artifact_path,
        matched_paths=[normalized],
        output_truncated=truncated,
    )


def _result(started: float, success: bool, summary: str) -> ToolResult:
    return ToolResult(tool=ToolKind.READ_FILE, success=success, summary=summary, duration_ms=_duration_ms(started))


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
