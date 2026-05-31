"""ReviewContext：把 diff、周边代码和仓库提示打包给 reviewer。"""

from __future__ import annotations

from pydantic import BaseModel

from pr_agent.diff.models import DiffHunk
from pr_agent.github.models import ChangedFile, PRInfo


class ReviewContext(BaseModel):
    pr: PRInfo
    file: ChangedFile
    hunks: list[DiffHunk]
    target_file_patch: str
    surrounding_code: str | None = None
    related_test_files: list[str]
    repo_readme_excerpt: str | None = None
