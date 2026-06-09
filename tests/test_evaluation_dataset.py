from pathlib import Path

from pr_agent.evaluation.dataset import (
    PredictionRecord,
    build_evaluation_report,
    load_evaluation_cases,
    score_predictions,
)


DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "cases.jsonl"


def test_evaluation_dataset_has_required_coverage():
    cases = load_evaluation_cases(DATASET_PATH)
    report = build_evaluation_report(cases)

    assert report["total_cases"] == 50
    assert report["task_counts"]["target_parser"] >= 7
    assert report["task_counts"]["issue_detection"] >= 14
    assert report["issue_category_counts"]["bug"] >= 3
    assert report["issue_category_counts"]["security"] >= 5


def test_score_predictions_reports_accuracy_and_issue_category_metrics():
    cases = load_evaluation_cases(DATASET_PATH)
    predictions = [
        PredictionRecord(case_id="TP001", passed=True),
        PredictionRecord(case_id="ID001", predicted_categories=["bug"]),
        PredictionRecord(case_id="ID003", predicted_categories=["security"]),
    ]

    metrics = score_predictions(cases, predictions)

    assert metrics["predictions_scored"] == 3
    assert metrics["accuracy"] == 1.0
    assert metrics["issue_category_precision"] == 1.0
    assert metrics["issue_category_recall"] == 1.0
    assert metrics["issue_category_f1"] == 1.0


def test_score_predictions_tracks_unknown_case_ids():
    cases = load_evaluation_cases(DATASET_PATH)
    metrics = score_predictions(cases, [PredictionRecord(case_id="missing", passed=True)])

    assert metrics["predictions_scored"] == 0
    assert metrics["unknown_case_ids"] == ["missing"]
