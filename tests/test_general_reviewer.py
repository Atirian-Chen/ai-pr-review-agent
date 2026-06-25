from pr_agent.agents.general_reviewer import GeneralReviewer
from pr_agent.context.models import ReviewContext
from pr_agent.diff.models import DiffHunk, DiffLine
from pr_agent.github.models import ChangedFile, PRInfo
from pr_agent.llm.client import LLMClient, LLMJsonResponse, LLMOutputError


class InvalidJsonLLM(LLMClient):
    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        raise LLMOutputError("bad json")


def test_general_reviewer_handles_invalid_json_without_crashing():
    summary, findings, stats = GeneralReviewer(InvalidJsonLLM()).review_context(_context())

    assert "invalid JSON" in summary
    assert findings == []
    assert stats["status"] == "invalid_json"


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
        related_test_files=[],
        repo_readme_excerpt=None,
    )
