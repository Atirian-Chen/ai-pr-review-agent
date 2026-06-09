"""Markdown 报告渲染：把结构化 ReviewResult 转成适合本地查看的报告。"""

from __future__ import annotations

from collections import Counter

from pr_agent.review.schema import ReviewResult


class MarkdownRenderer:
    def render(self, result: ReviewResult) -> str:
        lines: list[str] = [
            "# AI PR Review Report",
            "",
            "## Summary",
            result.summary.strip() or "No summary was generated.",
            "",
            "## Risk Level",
            self._risk_level(result),
            "",
            "## Findings",
        ]

        if not result.findings:
            lines.extend(["No high-confidence issues were found.", ""])
        else:
            for index, finding in enumerate(result.findings, start=1):
                location = finding.file_path
                if finding.line_start is not None:
                    location += f":{finding.line_start}"
                lines.extend(
                    [
                        f"### {index}. [{finding.severity.title()}][{finding.category}] {finding.title}",
                        f"- File: `{location}`",
                        f"- Confidence: {finding.confidence:.2f}",
                        f"- Evidence: {finding.evidence}",
                        f"- Why it matters: {finding.description}",
                        f"- Suggestion: {finding.suggestion}",
                    ]
                )
                if finding.suggested_patch:
                    lines.extend(["", "```suggestion", finding.suggested_patch.rstrip(), "```"])
                lines.append("")

        test_findings = [finding for finding in result.findings if finding.category == "test"]
        lines.extend(["## Test Suggestions"])
        if test_findings:
            lines.extend([f"- {finding.suggestion}" for finding in test_findings])
        else:
            lines.append("No specific test gaps were identified.")

        severity_counts = Counter(finding.severity for finding in result.findings)
        verification = result.stats.get("verification") or {}
        llm_verifier = result.stats.get("llm_verifier") or {}
        metrics = [
            "",
            "## Metrics",
            f"- Findings: {len(result.findings)}",
            f"- Critical: {severity_counts.get('critical', 0)}",
            f"- Major: {severity_counts.get('major', 0)}",
            f"- Minor: {severity_counts.get('minor', 0)}",
            f"- Nit: {severity_counts.get('nit', 0)}",
            f"- Model: {result.model_info.get('model', 'unknown')}",
            f"- Latency seconds: {result.stats.get('latency_seconds', 0):.2f}",
            f"- Estimated tokens: {result.stats.get('total_tokens', 0)}",
        ]
        if llm_verifier:
            verifier_label = llm_verifier.get("model") or llm_verifier.get("status", "unknown")
            metrics.append(f"- Verifier: {verifier_label}")
        if verification:
            metrics.extend(
                [
                    f"- Candidate findings: {verification.get('candidate_findings', 0)}",
                    f"- Suppressed candidates: {verification.get('suppressed_findings', 0)}",
                    f"- Published findings: {verification.get('published_findings', len(result.findings))}",
                ]
            )
        metrics.append("")
        lines.extend(metrics)
        return "\n".join(lines)

    def _risk_level(self, result: ReviewResult) -> str:
        severities = {finding.severity for finding in result.findings}
        if "critical" in severities:
            return "High"
        if "major" in severities:
            return "Medium"
        if result.findings:
            return "Low"
        return "None"
