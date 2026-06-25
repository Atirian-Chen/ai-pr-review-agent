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
    load_verification_cases,
    summarize_verification_cases,
)


DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "cases.jsonl"
PR_CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "pr_cases.jsonl"
VERIFICATION_CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "verification_cases.jsonl"


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


def test_verification_cases_have_supported_contradicted_and_inconclusive_coverage():
    cases = load_verification_cases(VERIFICATION_CASES_PATH)
    report = summarize_verification_cases(cases)

    assert report["total_verification_cases"] >= 12
    assert report["status_counts"]["supported"] >= 3
    assert report["status_counts"]["contradicted"] >= 3
    assert report["status_counts"]["inconclusive"] >= 3


def test_pr_evaluation_report_scores_verification_metrics():
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
                    verification_status="supported",
                    publication_decision="publish",
                ),
                PRPredictedFinding(
                    category="test",
                    file_path="src/api/profile.py",
                    line_start=42,
                    severity="minor",
                    confidence=0.7,
                    title="No tests exist",
                    verification_status="contradicted",
                    publication_decision="suppress",
                ),
                PRPredictedFinding(
                    category="performance",
                    file_path="src/api/profile.py",
                    line_start=42,
                    severity="minor",
                    confidence=0.7,
                    title="Maybe slow",
                    verification_status="inconclusive",
                    publication_decision="suppress",
                ),
            ],
            verification_latency_seconds=4.0,
            static_tool_calls=4,
            sandbox_tool_calls=2,
            llm_verifier_calls=1,
            sandbox_failures=1,
        )
    ]

    metrics = score_pr_predictions(cases, predictions)
    verification = metrics["verification"]

    assert verification["verification_coverage"] == 1.0
    assert verification["supported_finding_rate"] == 1 / 3
    assert verification["contradicted_suppression_rate"] == 1.0
    assert verification["inconclusive_rate"] == 1 / 3
    assert verification["sandbox_failure_rate"] == 0.5
    assert verification["tool_cost"]["static_tool_calls"] == 4
