from pathlib import Path

from pr_agent.evaluation.dataset import (
    PRPredictedFinding,
    PRPredictionRecord,
    PredictionRecord,
    build_evaluation_report,
    build_pr_evaluation_report,
    load_evaluation_cases,
    load_pr_evaluation_cases,
    score_predictions,
    score_pr_predictions,
)


DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "cases.jsonl"
PR_CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "pr_cases.jsonl"


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


def test_pr_evaluation_cases_have_required_size_and_categories():
    cases = load_pr_evaluation_cases(PR_CASES_PATH)
    report = build_pr_evaluation_report(cases)

    assert 20 <= report["total_pr_cases"] <= 30
    assert report["category_counts"]["bug"] >= 5
    assert report["category_counts"]["security"] >= 5
    assert report["category_counts"]["performance"] >= 5
    assert report["category_counts"]["test"] >= 5


def test_pr_evaluation_report_scores_quality_and_cost_metrics():
    cases = load_pr_evaluation_cases(PR_CASES_PATH)
    predictions = [
        PRPredictionRecord(
            case_id="PR001",
            findings=[
                PRPredictedFinding(
                    category="bug",
                    file_path="src/api/profile.py",
                    line_start=42,
                    severity="major",
                    confidence=0.9,
                    title="Unauthenticated branch can dereference a missing user",
                    has_patch_suggestion=True,
                    has_test_suggestion=True,
                ),
                PRPredictedFinding(
                    category="maintainability",
                    file_path="src/api/profile.py",
                    line_start=1,
                    severity="minor",
                    confidence=0.7,
                    title="Rename variable",
                ),
            ],
            latency_seconds=10.0,
            total_tokens=1000,
            cost_usd=0.01,
        )
    ]

    metrics = score_pr_predictions(cases, predictions)

    assert metrics["valid_finding_rate"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["line_hit_rate"] == 0.5
    assert metrics["fixability_rate"] == 1.0
    assert metrics["latency"]["average_seconds"] == 10.0
    assert metrics["token_cost"]["total_tokens"] == 1000
