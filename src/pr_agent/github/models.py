"""GitHub 数据模型：隔离 GitHub REST response 和项目内部结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PullRequestRef(BaseModel):
    owner: str
    repo: str
    pull_number: int = Field(gt=0)


SourceType = Literal["pull_request", "commit", "compare", "local_diff"]


class ReviewTargetInfo(BaseModel):
    source_type: SourceType = "pull_request"
    owner: str
    repo: str
    pull_number: int | None = None
    identifier: str = ""
    title: str
    body: str | None = None
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    author: str
    url: str


class PRInfo(ReviewTargetInfo):
    source_type: Literal["pull_request"] = "pull_request"
    pull_number: int = Field(gt=0)


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
        identifier=f"#{data['number']}",
        title=data.get("title") or "",
        body=data.get("body"),
        base_branch=data["base"]["ref"],
        head_branch=data["head"]["ref"],
        base_sha=data["base"]["sha"],
        head_sha=data["head"]["sha"],
        author=data.get("user", {}).get("login") or "",
        url=data.get("html_url") or "",
    )


def commit_info_from_api(data: dict, owner: str, repo: str) -> ReviewTargetInfo:
    commit = data.get("commit", {})
    message = commit.get("message") or data.get("sha", "")
    title, _, body = message.partition("\n")
    parent_sha = (data.get("parents") or [{}])[0].get("sha") or data.get("sha") or ""
    author = (
        data.get("author", {}).get("login")
        or commit.get("author", {}).get("name")
        or ""
    )
    sha = data.get("sha") or ""
    return ReviewTargetInfo(
        source_type="commit",
        owner=owner,
        repo=repo,
        identifier=sha,
        title=title or f"Commit {sha[:12]}",
        body=body or None,
        base_branch=parent_sha[:12] or "parent",
        head_branch=sha[:12] or "commit",
        base_sha=parent_sha,
        head_sha=sha,
        author=author,
        url=data.get("html_url") or f"https://github.com/{owner}/{repo}/commit/{sha}",
    )


def compare_info_from_api(data: dict, owner: str, repo: str, base_ref: str, head_ref: str) -> ReviewTargetInfo:
    base_sha = data.get("base_commit", {}).get("sha") or base_ref
    commits = data.get("commits") or []
    head_sha = commits[-1].get("sha") if commits else base_sha
    return ReviewTargetInfo(
        source_type="compare",
        owner=owner,
        repo=repo,
        identifier=f"{base_ref}...{head_ref}",
        title=f"Compare {base_ref}...{head_ref}",
        body=f"GitHub compare range from {base_ref} to {head_ref}.",
        base_branch=base_ref,
        head_branch=head_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        author="",
        url=data.get("html_url") or f"https://github.com/{owner}/{repo}/compare/{base_ref}...{head_ref}",
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
