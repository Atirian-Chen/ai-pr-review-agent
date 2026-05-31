"""Review 质量控制：过滤低置信度、无证据、行号不可信的 finding。"""

from __future__ import annotations

from pr_agent.diff.models import DiffHunk
from pr_agent.review.schema import ReviewFinding, ReviewResult


SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "nit": 3}


def validate_findings(
    result: ReviewResult,
    diff_hunks: list[DiffHunk],
    confidence_threshold: float = 0.6,
    max_findings: int = 8,
) -> ReviewResult:
    valid_files = {hunk.filename for hunk in diff_hunks}
    allowed_lines_by_file: dict[str, set[int]] = {}
    for hunk in diff_hunks:
        lines = allowed_lines_by_file.setdefault(hunk.filename, set())
        for line in hunk.lines:
            if line.new_line_no is not None:
                lines.add(line.new_line_no)

    filtered: list[ReviewFinding] = []
    for finding in result.findings:
        if not _is_high_signal(finding, valid_files, allowed_lines_by_file, confidence_threshold):
            continue
        filtered.append(finding)

    filtered.sort(key=lambda item: (SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_start or 0))
    return result.model_copy(update={"findings": filtered[:max_findings]})


def _is_high_signal(
    finding: ReviewFinding,
    valid_files: set[str],
    allowed_lines_by_file: dict[str, set[int]],
    confidence_threshold: float,
) -> bool:
    if finding.confidence < confidence_threshold:
        return False
    if finding.file_path not in valid_files:
        return False
    if finding.category == "style" and finding.severity == "nit":
        return False
    if not finding.evidence.strip() or not finding.suggestion.strip():
        return False

    # 行号为空时允许 file-level issue；有行号时必须落在 diff 上下文内，减少模型乱编行号。
    if finding.line_start is not None:
        allowed_lines = allowed_lines_by_file.get(finding.file_path, set())
        if finding.line_start not in allowed_lines:
            return False
    return True
