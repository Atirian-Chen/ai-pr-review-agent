"""Load and score JSONL evaluation datasets."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


CaseType = Literal[
    "target_parser",
    "diff_parser",
    "file_filter",
    "action_event",
    "comment_rendering",
    "issue_detection",
    "review_schema",
    "changeset_loader",
]
Difficulty = Literal["easy", "medium", "hard"]


class EvaluationCase(BaseModel):
    id: str
    task_type: CaseType
    title: str
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)
    difficulty: Difficulty = "medium"

    @field_validator("id", "title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()


class PredictionRecord(BaseModel):
    case_id: str
    passed: bool | None = None
    predicted_labels: list[str] = Field(default_factory=list)
    predicted_categories: list[str] = Field(default_factory=list)


class PRExpectedFinding(BaseModel):
    id: str
    category: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    severity: str = "minor"
    title: str
    fixable: bool = True


class PRCaseFile(BaseModel):
    path: str
    base: str = ""
    head: str


class PRCase(BaseModel):
    id: str
    title: str
    source: Literal["simulated", "real"] = "simulated"
    description: str
    changed_files: list[str]
    files: list[PRCaseFile] = Field(default_factory=list)
    expected_findings: list[PRExpectedFinding]
    labels: list[str] = Field(default_factory=list)
    difficulty: Difficulty = "medium"


class PRPredictedFinding(BaseModel):
    category: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    severity: str = "minor"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    title: str = ""
    has_patch_suggestion: bool = False
    has_test_suggestion: bool = False


class PRPredictionRecord(BaseModel):
    case_id: str
    findings: list[PRPredictedFinding] = Field(default_factory=list)
    latency_seconds: float | None = Field(default=None, ge=0.0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = EvaluationCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"Invalid evaluation case at {path}:{line_number}") from exc
        if case.id in seen_ids:
            raise ValueError(f"Duplicate evaluation case id {case.id!r} at {path}:{line_number}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def load_predictions(path: Path) -> list[PredictionRecord]:
    predictions: list[PredictionRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            predictions.append(PredictionRecord.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid prediction record at {path}:{line_number}") from exc
    return predictions


def load_pr_evaluation_cases(path: Path) -> list[PRCase]:
    cases: list[PRCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = PRCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"Invalid PR evaluation case at {path}:{line_number}") from exc
        if case.id in seen_ids:
            raise ValueError(f"Duplicate PR evaluation case id {case.id!r} at {path}:{line_number}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def load_pr_predictions(path: Path) -> list[PRPredictionRecord]:
    predictions: list[PRPredictionRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            predictions.append(PRPredictionRecord.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid PR prediction record at {path}:{line_number}") from exc
    return predictions


def summarize_evaluation_cases(cases: list[EvaluationCase]) -> dict[str, Any]:
    task_counts = Counter(case.task_type for case in cases)
    difficulty_counts = Counter(case.difficulty for case in cases)
    label_counts = Counter(label for case in cases for label in case.labels)
    issue_category_counts = Counter(
        category
        for case in cases
        if case.task_type == "issue_detection"
        for category in _expected_categories(case)
    )
    severity_counts = Counter(
        str(case.expected.get("severity"))
        for case in cases
        if case.task_type == "issue_detection" and case.expected.get("severity")
    )
    return {
        "total_cases": len(cases),
        "task_counts": dict(sorted(task_counts.items())),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
        "issue_category_counts": dict(sorted(issue_category_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
    }


def score_predictions(cases: list[EvaluationCase], predictions: list[PredictionRecord]) -> dict[str, Any]:
    case_by_id = {case.id: case for case in cases}
    pass_count = 0
    scored_count = 0
    unknown_case_ids: list[str] = []
    category_tp = 0
    category_fp = 0
    category_fn = 0

    for prediction in predictions:
        case = case_by_id.get(prediction.case_id)
        if case is None:
            unknown_case_ids.append(prediction.case_id)
            continue

        scored_count += 1
        passed = _prediction_passed(case, prediction)
        if passed:
            pass_count += 1

        if case.task_type == "issue_detection":
            expected_categories = set(_expected_categories(case))
            predicted_categories = set(prediction.predicted_categories)
            category_tp += len(expected_categories & predicted_categories)
            category_fp += len(predicted_categories - expected_categories)
            category_fn += len(expected_categories - predicted_categories)

    precision = _safe_div(category_tp, category_tp + category_fp)
    recall = _safe_div(category_tp, category_tp + category_fn)
    return {
        "predictions_scored": scored_count,
        "unknown_case_ids": unknown_case_ids,
        "accuracy": _safe_div(pass_count, scored_count),
        "passed": pass_count,
        "failed": scored_count - pass_count,
        "issue_category_precision": precision,
        "issue_category_recall": recall,
        "issue_category_f1": _safe_div(2 * precision * recall, precision + recall),
    }


def build_evaluation_report(cases: list[EvaluationCase], predictions: list[PredictionRecord] | None = None) -> dict[str, Any]:
    report = summarize_evaluation_cases(cases)
    if predictions is not None:
        report["metrics"] = score_predictions(cases, predictions)
    return report


def summarize_pr_cases(cases: list[PRCase]) -> dict[str, Any]:
    category_counts = Counter(finding.category for case in cases for finding in case.expected_findings)
    difficulty_counts = Counter(case.difficulty for case in cases)
    label_counts = Counter(label for case in cases for label in case.labels)
    return {
        "total_pr_cases": len(cases),
        "total_expected_findings": sum(len(case.expected_findings) for case in cases),
        "category_counts": dict(sorted(category_counts.items())),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
    }


def score_pr_predictions(
    cases: list[PRCase],
    predictions: list[PRPredictionRecord],
    line_tolerance: int = 3,
) -> dict[str, Any]:
    case_by_id = {case.id: case for case in cases}
    total_predictions = 0
    valid_predictions = 0
    false_positive_predictions = 0
    expected_with_line = 0
    line_hits = 0
    fixable_matches = 0
    fixable_with_suggestion = 0
    unknown_case_ids: list[str] = []
    latencies: list[float] = []
    token_counts: list[int] = []
    total_cost = 0.0

    for prediction in predictions:
        case = case_by_id.get(prediction.case_id)
        if case is None:
            unknown_case_ids.append(prediction.case_id)
            continue
        if prediction.latency_seconds is not None:
            latencies.append(prediction.latency_seconds)
        if prediction.total_tokens is not None:
            token_counts.append(prediction.total_tokens)
        if prediction.cost_usd is not None:
            total_cost += prediction.cost_usd

        matched_expected: set[str] = set()
        for predicted_finding in prediction.findings:
            total_predictions += 1
            match = _match_expected_finding(case.expected_findings, predicted_finding, matched_expected, line_tolerance)
            if match is None:
                false_positive_predictions += 1
                continue

            valid_predictions += 1
            matched_expected.add(match.id)
            if match.line_start is not None:
                line_hits += 1
            if match.fixable:
                fixable_matches += 1
                if predicted_finding.has_patch_suggestion or predicted_finding.has_test_suggestion:
                    fixable_with_suggestion += 1

        expected_with_line += sum(1 for finding in case.expected_findings if finding.line_start is not None)

    return {
        "predictions_scored": len(predictions) - len(unknown_case_ids),
        "unknown_case_ids": unknown_case_ids,
        "valid_finding_rate": _safe_div(valid_predictions, total_predictions),
        "line_hit_rate": _safe_div(line_hits, expected_with_line),
        "false_positive_rate": _safe_div(false_positive_predictions, total_predictions),
        "fixability_rate": _safe_div(fixable_with_suggestion, fixable_matches),
        "valid_findings": valid_predictions,
        "false_positive_findings": false_positive_predictions,
        "predicted_findings": total_predictions,
        "latency": {
            "average_seconds": _average(latencies),
            "p95_seconds": _percentile(latencies, 0.95),
            "total_seconds": sum(latencies),
        },
        "token_cost": {
            "average_tokens": _average(token_counts),
            "total_tokens": sum(token_counts),
            "total_cost_usd": total_cost,
        },
    }


def build_pr_evaluation_report(
    cases: list[PRCase],
    predictions: list[PRPredictionRecord] | None = None,
    line_tolerance: int = 3,
) -> dict[str, Any]:
    report = summarize_pr_cases(cases)
    if predictions is not None:
        report["metrics"] = score_pr_predictions(cases, predictions, line_tolerance=line_tolerance)
    return report


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def _prediction_passed(case: EvaluationCase, prediction: PredictionRecord) -> bool:
    if prediction.passed is not None:
        return prediction.passed

    expected_labels = set(case.expected.get("labels") or case.labels)
    if prediction.predicted_labels:
        return set(prediction.predicted_labels) == expected_labels

    if case.task_type == "issue_detection":
        return set(prediction.predicted_categories) == set(_expected_categories(case))

    return False


def _expected_categories(case: EvaluationCase) -> list[str]:
    categories = case.expected.get("issue_categories")
    if isinstance(categories, list):
        return [str(category) for category in categories]
    category = case.expected.get("category")
    return [str(category)] if category else []


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _match_expected_finding(
    expected_findings: list[PRExpectedFinding],
    predicted: PRPredictedFinding,
    used_ids: set[str],
    line_tolerance: int,
) -> PRExpectedFinding | None:
    for expected in expected_findings:
        if expected.id in used_ids:
            continue
        if expected.category != predicted.category or expected.file_path != predicted.file_path:
            continue
        if expected.line_start is None:
            return expected
        if predicted.line_start is None:
            continue
        if abs(expected.line_start - predicted.line_start) <= line_tolerance:
            return expected
    return None


def _average(values: list[float] | list[int]) -> float:
    return _safe_div(float(sum(values)), len(values))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(int(round((len(sorted_values) - 1) * percentile)), len(sorted_values) - 1)
    return sorted_values[index]
