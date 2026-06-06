"""统一变更集模型：让 PR、commit、compare、local diff 进入同一条 review 管线。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pr_agent.diff.models import DiffHunk
from pr_agent.github.models import ChangedFile, ReviewTargetInfo


TargetKind = Literal["pull_request", "commit", "compare", "local_diff"]


class ReviewTargetRef(BaseModel):
    source_type: TargetKind
    owner: str | None = None
    repo: str | None = None
    pull_number: int | None = None
    commit_sha: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    url: str | None = None


class ChangeSet(BaseModel):
    target: ReviewTargetInfo
    files: list[ChangedFile]
    hunks_by_file: dict[str, list[DiffHunk]]
