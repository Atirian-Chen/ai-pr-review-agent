"""ChangeSet loader：把不同来源的变更统一成 files + hunks_by_file。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pr_agent.diff.full_parser import parse_full_unified_diff
from pr_agent.diff.parser import parse_patch
from pr_agent.github.client import GitHubClient
from pr_agent.github.models import ReviewTargetInfo
from pr_agent.targets.models import ChangeSet, ReviewTargetRef
from pr_agent.targets.parser import parse_review_target


class ChangeSetLoader:
    def __init__(self, github_client: GitHubClient, repo_root: Path | None = None) -> None:
        self.github_client = github_client
        self.repo_root = repo_root or Path.cwd()

    def load(self, target: str) -> ChangeSet:
        ref = parse_review_target(target)
        if ref.source_type == "pull_request":
            pr = self.github_client.get_pull_request(ref.owner or "", ref.repo or "", ref.pull_number or 0)
            files = self.github_client.list_pull_request_files(pr.owner, pr.repo, pr.pull_number)
            return _build_change_set(pr, files)

        if ref.source_type == "commit":
            info, files = self.github_client.get_commit(ref.owner or "", ref.repo or "", ref.commit_sha or "")
            return _build_change_set(info, files)

        if ref.source_type == "compare":
            info, files = self.github_client.compare_commits(
                ref.owner or "",
                ref.repo or "",
                ref.base_ref or "",
                ref.head_ref or "",
            )
            return _build_change_set(info, files)

        return self._load_local_diff()

    def _load_local_diff(self) -> ChangeSet:
        diff_text = _run_git(["diff", "--no-ext-diff", "--unified=3", "HEAD", "--", "."], self.repo_root)
        files = parse_full_unified_diff(diff_text)
        head_sha = _run_git(["rev-parse", "--verify", "HEAD"], self.repo_root)
        branch = _run_git(["branch", "--show-current"], self.repo_root) or "HEAD"
        author = _run_git_optional(["config", "user.name"], self.repo_root)
        repo_name = self.repo_root.resolve().name
        info = ReviewTargetInfo(
            source_type="local_diff",
            owner="local",
            repo=repo_name,
            identifier="local",
            title=f"Local git diff in {repo_name}",
            body="Uncommitted local changes compared with HEAD.",
            base_branch=branch,
            head_branch="working-tree",
            base_sha=head_sha,
            head_sha="WORKTREE",
            author=author,
            url=str(self.repo_root.resolve()),
        )
        return _build_change_set(info, files)


def _build_change_set(target: ReviewTargetInfo, files) -> ChangeSet:
    hunks_by_file = {file.filename: parse_patch(file.filename, file.patch) for file in files}
    return ChangeSet(target=target, files=files, hunks_by_file=hunks_by_file)


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def _run_git_optional(args: list[str], cwd: Path) -> str:
    try:
        return _run_git(args, cwd)
    except subprocess.CalledProcessError:
        return ""
