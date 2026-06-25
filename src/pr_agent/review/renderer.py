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
                        f"- Reviewer: `{finding.reviewer}`",
                        f"- Confidence: {finding.confidence:.2f}",
                        f"- Evidence: {finding.evidence}",
                        f"- Why it matters: {finding.description}",
                        f"- Suggestion: {finding.suggestion}",
                    ]
                )
                if finding.verification:
                    lines.extend(self._verification_lines(finding))
                if finding.patch_suggestion:
                    lines.extend(
                        [
                            "",
                            "**Patch Suggestion**",
                            f"- Plan: {finding.patch_suggestion.description}",
                        ]
                    )
                    if finding.patch_suggestion.commands:
                        lines.extend([f"- Validate: `{command}`" for command in finding.patch_suggestion.commands])
                    if finding.patch_suggestion.suggested_patch:
                        lines.extend(["", "```diff", finding.patch_suggestion.suggested_patch.rstrip(), "```"])
                if finding.test_suggestions:
                    lines.extend(["", "**Test Suggestions**"])
                    for test_suggestion in finding.test_suggestions:
                        target = f" in `{test_suggestion.test_file_path}`" if test_suggestion.test_file_path else ""
                        lines.append(f"- `{test_suggestion.test_name}`{target}: {test_suggestion.scenario}")
                        lines.extend([f"  - Assert: {assertion}" for assertion in test_suggestion.assertions])
                        if test_suggestion.suggested_test_code:
                            lines.extend(["", "```python", test_suggestion.suggested_test_code.rstrip(), "```"])
                if finding.suggested_patch:
                    lines.extend(["", "```suggestion", finding.suggested_patch.rstrip(), "```"])
                lines.append("")

        test_findings = [finding for finding in result.findings if finding.category == "test"]
        lines.extend(["## Test Suggestions"])
        if test_findings:
            for finding in test_findings:
                if finding.test_suggestions:
                    for test_suggestion in finding.test_suggestions:
                        target = f" in `{test_suggestion.test_file_path}`" if test_suggestion.test_file_path else ""
                        lines.append(f"- `{test_suggestion.test_name}`{target}: {test_suggestion.scenario}")
                else:
                    lines.append(f"- {finding.suggestion}")
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
                    f"- Verification mode: {verification.get('mode', 'deterministic')}",
                    f"- Verification coverage: {verification.get('verification_coverage', 0):.2%}",
                    f"- Supported finding rate: {verification.get('supported_finding_rate', 0):.2%}",
                    f"- Contradicted suppression rate: {verification.get('contradicted_suppression_rate', 0):.2%}",
                    f"- Inconclusive rate: {verification.get('inconclusive_rate', 0):.2%}",
                    f"- Suppressed candidates: {verification.get('suppressed_findings', 0)}",
                    f"- Published findings: {verification.get('published_findings', len(result.findings))}",
                ]
            )
        metrics.append("")
        lines.extend(metrics)
        return "\n".join(lines)

    def _verification_lines(self, finding) -> list[str]:
        verification = finding.verification
        status_label = {
            "supported": "Supported",
            "contradicted": "Contradicted",
            "inconclusive": "Inconclusive",
            "skipped": "Skipped",
            "not_eligible": "Not eligible",
            "not_requested": "Not requested",
            "error": "Error",
        }.get(verification.status.value, verification.status.value)
        lines = [
            f"- Reviewer confidence: {verification.confidence_before:.2f} -> {verification.confidence_after:.2f}",
            f"- Verification: {status_label}",
            f"- Publication decision: `{verification.publication_decision}`",
            f"- Evidence summary: {verification.evidence_summary}",
        ]
        if verification.tool_results:
            lines.append("- Tool evidence:")
            for result in verification.tool_results:
                command_hint = ""
                if result.tool.value in {"pytest", "ruff", "mypy"} and result.matched_paths:
                    command_hint = f" on `{', '.join(result.matched_paths[:2])}`"
                lines.append(f"  - `{result.tool.value}`{command_hint}: {result.summary}")
        return lines

    def _risk_level(self, result: ReviewResult) -> str:
        severities = {finding.severity for finding in result.findings}
        if "critical" in severities:
            return "High"
        if "major" in severities:
            return "Medium"
        if result.findings:
            return "Low"
        return "None"
