from pr_agent.agents.multi_agent_reviewer import MultiAgentReviewer
from pr_agent.context.models import ReviewContext
from pr_agent.diff.models import DiffHunk, DiffLine
from pr_agent.github.models import ChangedFile, PRInfo
from pr_agent.llm.client import LLMClient, LLMJsonResponse


class FakeLLM(LLMClient):
    def __init__(self):
        self.calls = 0
        self.responses = [
            {
                "summary": "bug found",
                "findings": [
                    {
                        "file_path": "src/app.py",
                        "line_start": 2,
                        "line_end": 2,
                        "category": "bug",
                        "severity": "major",
                        "confidence": 0.9,
                        "title": "None branch can fail",
                        "description": "The new branch returns None.",
                        "evidence": "+ return None",
                        "suggestion": "Return a value or raise.",
                        "patch_suggestion": {
                            "description": "Replace the None return.",
                            "suggested_patch": "- return None\n+ raise ValueError()",
                            "commands": ["python -m pytest"],
                        },
                    }
                ],
            },
            {
                "summary": "test found",
                "findings": [
                    {
                        "file_path": "tests/test_app.py",
                        "line_start": 4,
                        "line_end": 4,
                        "category": "test",
                        "severity": "minor",
                        "confidence": 0.8,
                        "title": "Missing None branch test",
                        "description": "The new branch has no regression test.",
                        "evidence": "+ return None",
                        "suggestion": "Add a regression test.",
                        "test_suggestions": [
                            {
                                "test_file_path": "tests/test_app.py",
                                "test_name": "test_none_branch",
                                "scenario": "Input triggers the None branch.",
                                "assertions": ["The branch raises a controlled error."],
                            }
                        ],
                    }
                ],
            },
            {"summary": "security clean", "findings": []},
            {"summary": "performance clean", "findings": []},
        ]

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        response = self.responses[self.calls]
        self.calls += 1
        return LLMJsonResponse(data=response, latency_seconds=0.1, model="fake-model", usage={"total_tokens": 10})


def _context() -> ReviewContext:
    pr = PRInfo(
        owner="acme",
        repo="app",
        pull_number=1,
        identifier="#1",
        title="Test",
        body=None,
        base_branch="main",
        head_branch="feature",
        base_sha="base",
        head_sha="head",
        author="alice",
        url="https://github.com/acme/app/pull/1",
    )
    file = ChangedFile(filename="src/app.py", status="modified", additions=1, deletions=0, changes=1, patch="@@\n+return None")
    hunk = DiffHunk(
        filename="src/app.py",
        old_start=1,
        old_count=0,
        new_start=2,
        new_count=1,
        section_header=None,
        lines=[DiffLine(line_type="add", content="return None", old_line_no=None, new_line_no=2)],
    )
    return ReviewContext(
        pr=pr,
        file=file,
        hunks=[hunk],
        target_file_patch=file.patch or "",
        surrounding_code="2: return None",
        related_test_files=["tests/test_app.py"],
        repo_readme_excerpt=None,
    )


def test_multi_agent_reviewer_runs_specialized_reviewers_and_preserves_suggestions():
    llm = FakeLLM()
    reviewer = MultiAgentReviewer(llm)

    summary, findings, stats = reviewer.review_context(_context())

    assert llm.calls == 4
    assert "Bug Reviewer" in summary
    assert [finding.reviewer for finding in findings] == ["bug", "test"]
    assert findings[0].patch_suggestion is not None
    assert findings[1].test_suggestions[0].test_name == "test_none_branch"
    assert stats["reviewer_mode"] == "multi_agent"
    assert stats["coordinator"]["input_findings"] == 2
