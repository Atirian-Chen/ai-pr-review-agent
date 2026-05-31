"""GitHub 数据模型：隔离 GitHub REST response 和项目内部结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PullRequestRef(BaseModel):
    owner: str
    repo: str
    pull_number: int = Field(gt=0)


class PRInfo(BaseModel):
    owner: str
    repo: str
    pull_number: int
    title: str
    body: str | None = None
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    author: str
    url: str


class ChangedFile(BaseModel):
    filename: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    changes: int
    patch: str | None = None
    raw_url: str | None = None
    previous_filename: str | None = None


def pr_info_from_api(data: dict, owner: str, repo: str) -> PRInfo:
    return PRInfo(
        owner=owner,
        repo=repo,
        pull_number=data["number"],
        title=data.get("title") or "",
        body=data.get("body"),
        base_branch=data["base"]["ref"],
        head_branch=data["head"]["ref"],
        base_sha=data["base"]["sha"],
        head_sha=data["head"]["sha"],
        author=data.get("user", {}).get("login") or "",
        url=data.get("html_url") or "",
    )


def changed_file_from_api(data: dict) -> ChangedFile:
    return ChangedFile(
        filename=data["filename"],
        status=data["status"],
        additions=data.get("additions", 0),
        deletions=data.get("deletions", 0),
        changes=data.get("changes", 0),
        patch=data.get("patch"),
        raw_url=data.get("raw_url"),
        previous_filename=data.get("previous_filename"),
    )
