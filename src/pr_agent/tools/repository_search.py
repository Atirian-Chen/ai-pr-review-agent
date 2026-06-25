"""Read-only repository search with strict file and result limits."""

from __future__ import annotations

import time
from pathlib import Path

from pr_agent.review.schema import ToolKind, ToolResult
from pr_agent.tools.base import should_skip_path, truncate_text, write_json_artifact


DEFAULT_MAX_FILES = 1000
DEFAULT_MAX_FILE_BYTES = 512_000
DEFAULT_MAX_RESULTS = 50
DEFAULT_MAX_SUMMARY_CHARS = 500


def repository_search(
    repo_root: Path,
    search_terms: list[str],
    artifact_dir: Path | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> ToolResult:
    started = time.perf_counter()
    terms = _clean_terms(search_terms)
    if not terms:
        return ToolResult(
            tool=ToolKind.REPOSITORY_SEARCH,
            success=True,
            summary="No search terms were supplied.",
            duration_ms=_duration_ms(started),
        )

    matches: list[dict[str, object]] = []
    scanned_files = 0
    truncated = False

    for path in repo_root.rglob("*"):
        if scanned_files >= max_files:
            truncated = True
            break
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if should_skip_path(relative):
            continue

        scanned_files += 1
        try:
            if path.stat().st_size > max_file_bytes:
                truncated = True
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        for line_number, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            if any(term.lower() in lower for term in terms):
                snippet, was_truncated = truncate_text(line.strip(), DEFAULT_MAX_SUMMARY_CHARS)
                truncated = truncated or was_truncated
                matches.append({"path": relative, "line": line_number, "snippet": snippet})
                if len(matches) >= max_results:
                    truncated = True
                    break
        if len(matches) >= max_results:
            break

    matched_paths = list(dict.fromkeys(str(item["path"]) for item in matches))
    matched_lines = [int(item["line"]) for item in matches[:max_results]]
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_json_artifact(
            artifact_dir / "search_result.json",
            {
                "terms": terms,
                "scanned_files": scanned_files,
                "matches": matches,
                "truncated": truncated,
            },
        )
    summary = f"Found {len(matches)} match(es) in {len(matched_paths)} file(s) for {', '.join(terms[:5])}."
    if truncated:
        summary += " Output was truncated by search limits."
    return ToolResult(
        tool=ToolKind.REPOSITORY_SEARCH,
        success=True,
        summary=summary,
        duration_ms=_duration_ms(started),
        artifact_path=artifact_path,
        matched_paths=matched_paths,
        matched_lines=matched_lines,
        output_truncated=truncated,
    )


def _clean_terms(search_terms: list[str]) -> list[str]:
    terms = [term.strip() for term in search_terms if term and term.strip()]
    return list(dict.fromkeys(terms))[:8]


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
