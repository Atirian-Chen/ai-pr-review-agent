"""Markdown summary comments for GitHub PRs and commits."""

from __future__ import annotations

from collections import Counter

from pr_agent.review.schema import ReviewResult


SUMMARY_COMMENT_MARKER = "<!-- ai-pr-review-agent:summary-comment -->"


def build_summary_comment(result: ReviewResult, max_findings: int = 8) -> str:
    target = result.pr
    severity_counts = Counter(finding.severity for finding in result.findings)
    lines = [
        SUMMARY_COMMENT_MARKER,
        "## AI Review Summary",
        "",
        f"- Target: `{target.source_type}` `{target.identifier}`",
        f"- Risk: {_risk_level(result)}",
        f"- Files reviewed: {result.stats.get('files_reviewed', 0)} / {result.stats.get('files_seen', 0)}",
        f"- Findings: {len(result.findings)}",
        f"- Critical: {severity_counts.get('critical', 0)}",
        f"- Major: {severity_counts.get('major', 0)}",
        f"- Minor: {severity_counts.get('minor', 0)}",
        f"- Nit: {severity_counts.get('nit', 0)}",
        f"- Model: {result.model_info.get('model', 'unknown')}",
        "",
        "### Summary",
        result.summary.strip() or "No summary was generated.",
        "",
        "### Findings",
    ]

    if not result.findings:
        lines.append("No high-confidence issues were found.")
    else:
        for index, finding in enumerate(result.findings[:max_findings], start=1):
            location = finding.file_path
            if finding.line_start is not None:
                location += f":{finding.line_start}"
            lines.append(
                f"{index}. **{finding.severity.title()} / {finding.category}** "
                f"`{location}`: {finding.title} ({finding.confidence:.2f})"
            )
        hidden_count = len(result.findings) - max_findings
        if hidden_count > 0:
            lines.append(f"{hidden_count} additional finding(s) omitted from this summary comment.")

    if result.trace_id:
        lines.extend(["", f"Trace: `{result.trace_id}`"])

    return "\n".join(lines).strip() + "\n"


def _risk_level(result: ReviewResult) -> str:
    severities = {finding.severity for finding in result.findings}
    if "critical" in severities:
        return "High"
    if "major" in severities:
        return "Medium"
    if result.findings:
        return "Low"
    return "None"
