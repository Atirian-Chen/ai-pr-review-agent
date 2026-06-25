import json
from pathlib import Path

from pr_agent.config import AppConfig
from pr_agent.evaluation.dataset import load_live_e2e_cases
from pr_agent.evaluation.runner import run_live_e2e
from pr_agent.review.runner import ReviewRun
from pr_agent.review.schema import ReviewResult


def test_live_e2e_cases_cover_positive_negative_mixed_and_hard_cases():
    cases = load_live_e2e_cases(Path("evaluation/live_e2e_cases.jsonl"))
    labels = {label for case in cases for label in case.labels}
    suffixes = {Path(case_file.path).suffix for case in cases for case_file in case.files}

    assert len(cases) >= 20
    assert ".py" in suffixes
    assert ".cpp" in suffixes
    assert "positive" in labels
    assert "negative" in labels
    assert "mixed" in labels
    assert "hard-to-detect" in labels
    assert "build-breaker" in labels
    assert "conditional-crash" in labels
    assert "logic-bug" in labels
    assert "concurrency" in labels
    assert "resource-leak" in labels
    assert "memory-leak" in labels
    assert any(case.clean_case for case in cases)
    assert any(case.expected_issue_count > 1 for case in cases)


def test_run_live_e2e_writes_manifest_without_scoring(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "id": "LIVE_TEST",
                "title": "Clean refactor",
                "description": "No issue expected.",
                "files": [
                    {
                        "path": "src/app.py",
                        "base": "def value():\n    return 1\n",
                        "head": "def value():\n    result = 1\n    return result\n",
                    }
                ],
                "expected_issues": [],
                "expected_issue_count": 0,
                "clean_case": True,
                "labels": ["negative"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_review(change_set, cfg, repo_root=None, verification_options=None):
        result = ReviewResult(
            pr=change_set.target,
            summary="fake clean review",
            findings=[],
            stats={"verification": {"mode": verification_options.mode if verification_options else "off"}},
            model_info={"model": "fake"},
        )
        return ReviewRun(result=result, change_set=change_set, reviewable_files=change_set.files, trace_rows=[])

    monkeypatch.setattr("pr_agent.evaluation.runner.run_review_on_change_set", fake_review)
    run_live_e2e(cases_path, tmp_path / "out", AppConfig(), verify_mode="static")

    manifest = json.loads((tmp_path / "out" / "case_manifest.json").read_text(encoding="utf-8"))
    case = manifest["cases"][0]

    assert manifest["manual_judgement"]["status"] == "not_scored_by_tool"
    assert "precision" not in manifest
    assert case["expected_issue_count"] == 0
    assert case["status"] == "completed"
    assert (tmp_path / "out" / "cases" / "LIVE_TEST" / "review_result.json").exists()
    assert (tmp_path / "out" / "cases" / "LIVE_TEST" / "expected_case.json").exists()
