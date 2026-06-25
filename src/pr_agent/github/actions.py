"""Helpers for resolving GitHub Actions events into review targets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


CommentTargetType = Literal["pull_request", "commit"]


class GitHubActionSkip(RuntimeError):
    """Raised when a GitHub Actions event has nothing reviewable."""


@dataclass(frozen=True)
class GitHubActionReviewTarget:
    target: str
    comment_target_type: CommentTargetType
    owner: str
    repo: str
    event_name: str
    pull_number: int | None = None
    commit_sha: str | None = None
    is_fork_pull_request: bool = False


def resolve_action_review_target(
    event_name: str | None = None,
    event_path: str | Path | None = None,
    repository: str | None = None,
    server_url: str | None = None,
) -> GitHubActionReviewTarget:
    payload = _load_event_payload(event_path)
    resolved_event_name = event_name or os.getenv("GITHUB_EVENT_NAME") or ""
    if not resolved_event_name:
        raise ValueError("GITHUB_EVENT_NAME is required to resolve a GitHub Actions review target")

    repo_full_name = repository or os.getenv("GITHUB_REPOSITORY") or _payload_repo_full_name(payload)
    owner, repo = _split_repo_full_name(repo_full_name)
    base_url = (server_url or os.getenv("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")

    if resolved_event_name in {"pull_request", "pull_request_target"}:
        pr_payload = payload.get("pull_request") or {}
        pull_number = int(pr_payload.get("number") or payload.get("number") or 0)
        if pull_number <= 0:
            raise ValueError("pull_request event payload does not contain a valid PR number")
        target = pr_payload.get("html_url") or f"{base_url}/{owner}/{repo}/pull/{pull_number}"
        is_fork = _is_fork_pull_request(pr_payload, repo_full_name)
        return GitHubActionReviewTarget(
            target=target,
            comment_target_type="pull_request",
            owner=owner,
            repo=repo,
            event_name=resolved_event_name,
            pull_number=pull_number,
            is_fork_pull_request=is_fork,
        )

    if resolved_event_name == "push":
        before_sha = str(payload.get("before") or "")
        after_sha = str(payload.get("after") or os.getenv("GITHUB_SHA") or "")
        if _is_zero_sha(after_sha) or not after_sha:
            raise GitHubActionSkip("push event does not have a reviewable head commit")

        if before_sha and not _is_zero_sha(before_sha):
            target = f"{base_url}/{owner}/{repo}/compare/{before_sha}...{after_sha}"
        else:
            target = f"{base_url}/{owner}/{repo}/commit/{after_sha}"

        return GitHubActionReviewTarget(
            target=target,
            comment_target_type="commit",
            owner=owner,
            repo=repo,
            event_name=resolved_event_name,
            commit_sha=after_sha,
        )

    raise GitHubActionSkip(f"GitHub Actions event {resolved_event_name!r} is not configured for review")


def _load_event_payload(event_path: str | Path | None) -> dict:
    raw_path = event_path or os.getenv("GITHUB_EVENT_PATH")
    if not raw_path:
        raise ValueError("GITHUB_EVENT_PATH is required to resolve a GitHub Actions review target")
    resolved_path = Path(raw_path)
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"GitHub Actions event payload file does not exist: {resolved_path}") from exc
    if not isinstance(data, dict):
        raise ValueError("GitHub Actions event payload must be a JSON object")
    return data


def _payload_repo_full_name(payload: dict) -> str:
    repository = payload.get("repository") or {}
    full_name = repository.get("full_name")
    if not full_name:
        raise ValueError("GitHub Actions event payload does not include repository.full_name")
    return str(full_name)


def _split_repo_full_name(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid GitHub repository full name: {repo_full_name!r}")
    return parts[0], parts[1]


def _is_zero_sha(value: str) -> bool:
    return bool(value) and set(value) == {"0"}


def _is_fork_pull_request(pr_payload: dict, base_repo_full_name: str) -> bool:
    head_repo = (pr_payload.get("head") or {}).get("repo") or {}
    head_full_name = head_repo.get("full_name")
    if not head_full_name:
        return False
    return str(head_full_name).lower() != base_repo_full_name.lower()
