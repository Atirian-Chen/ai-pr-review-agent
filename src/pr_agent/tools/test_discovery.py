"""Find likely tests related to a changed source file or finding."""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath

from pr_agent.context.retriever import infer_related_test_files
from pr_agent.review.schema import ReviewFinding, ToolKind, ToolResult
from pr_agent.tools.base import is_safe_relative_path, normalize_repo_path, should_skip_path, write_json_artifact


DEFAULT_MAX_TESTS = 20


def discover_tests(
    repo_root: Path,
    finding: ReviewFinding,
    search_terms: list[str] | None = None,
    artifact_dir: Path | None = None,
    max_tests: int = DEFAULT_MAX_TESTS,
) -> tuple[ToolResult, list[str]]:
    started = time.perf_counter()
    terms = [term.lower() for term in (search_terms or []) if term and term.strip()]
    candidates = _candidate_paths(repo_root, finding, terms, max_tests=max_tests)
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_json_artifact(
            artifact_dir / "test_discovery.json",
            {
                "finding_id": finding.id,
                "source_file": finding.file_path,
                "search_terms": terms,
                "candidate_test_paths": candidates,
                "confidence": _confidence(candidates),
                "reason": _reason(candidates, finding.file_path),
            },
        )
    summary = _reason(candidates, finding.file_path)
    return (
        ToolResult(
            tool=ToolKind.TEST_DISCOVERY,
            success=True,
            summary=summary,
            duration_ms=_duration_ms(started),
            artifact_path=artifact_path,
            matched_paths=candidates,
        ),
        candidates,
    )


def _candidate_paths(repo_root: Path, finding: ReviewFinding, terms: list[str], max_tests: int) -> list[str]:
    ordered: list[str] = []
    for test_suggestion in finding.test_suggestions:
        if test_suggestion.test_file_path:
            ordered.append(test_suggestion.test_file_path)
    if finding.verification_intent and finding.verification_intent.candidate_test_file:
        ordered.append(finding.verification_intent.candidate_test_file)
    ordered.extend(infer_related_test_files(finding.file_path))

    source_stem = PurePosixPath(finding.file_path).stem.lower()
    source_parent = PurePosixPath(finding.file_path).parent.name.lower()
    for path in repo_root.rglob("*.py"):
        try:
            relative = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if should_skip_path(relative) or not _looks_like_test(relative):
            continue
        lower = relative.lower()
        if source_stem in lower or source_parent in lower or any(term in lower for term in terms):
            ordered.append(relative)

    existing = []
    for path in ordered:
        normalized = normalize_repo_path(path)
        if not is_safe_relative_path(normalized) or should_skip_path(normalized):
            continue
        if (repo_root / normalized).is_file():
            existing.append(normalized)
    return list(dict.fromkeys(existing))[:max_tests]


def _looks_like_test(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in {part.lower() for part in pure.parts}


def _confidence(candidates: list[str]) -> float:
    if not candidates:
        return 0.0
    return 0.8 if len(candidates) <= 3 else 0.6


def _reason(candidates: list[str], source_file: str) -> str:
    if not candidates:
        return f"No related test files were found for {source_file}."
    return f"Found {len(candidates)} candidate test file(s) for {source_file}: {', '.join(candidates[:5])}."


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
