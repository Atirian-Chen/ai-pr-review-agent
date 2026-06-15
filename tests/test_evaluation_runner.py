import json

from pr_agent.config import AppConfig
from pr_agent.evaluation.runner import run_pr_evaluation


def test_run_pr_evaluation_materializes_cases_and_writes_outputs(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "id": "RUNTEST",
                "title": "SQL interpolation",
                "source": "simulated",
                "description": "Search query uses f-string SQL.",
                "changed_files": ["src/search/repository.py"],
                "files": [
                    {
                        "path": "src/search/repository.py",
                        "base": "def search(conn, term):\n    return conn.execute('SELECT 1')\n",
                        "head": "def search(conn, term):\n    sql = f\"SELECT * FROM docs WHERE title LIKE '%{term}%'\"\n    return conn.execute(sql)\n",
                    }
                ],
                "expected_findings": [
                    {
                        "id": "RUNTEST-SEC",
                        "category": "security",
                        "file_path": "src/search/repository.py",
                        "line_start": 2,
                        "severity": "critical",
                        "title": "User input is interpolated into SQL",
                        "fixable": True,
                    }
                ],
                "labels": ["security"],
                "difficulty": "medium",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_pr_evaluation(cases_path, tmp_path / "run", AppConfig(), llm_mode="deterministic")

    assert result.report["total_pr_cases"] == 1
    assert result.report["metrics"]["valid_finding_rate"] == 1.0
    assert (tmp_path / "run" / "pr_predictions.jsonl").exists()
    assert (tmp_path / "run" / "evaluation_report.json").exists()
    assert (tmp_path / "run" / "cases" / "RUNTEST" / "review_result.json").exists()
