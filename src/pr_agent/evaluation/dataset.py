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
