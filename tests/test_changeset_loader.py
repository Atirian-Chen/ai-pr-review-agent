import subprocess

from pr_agent.github.models import ChangedFile, PRInfo, ReviewTargetInfo
from pr_agent.targets.loader import ChangeSetLoader


class FakeGitHubClient:
    def get_pull_request(self, owner, repo, pull_number):
        return PRInfo(
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            identifier=f"#{pull_number}",
            title="PR title",
            body=None,
            base_branch="main",
            head_branch="feature",
            base_sha="base",
            head_sha="head",
            author="alice",
            url=f"https://github.com/{owner}/{repo}/pull/{pull_number}",
        )

    def list_pull_request_files(self, owner, repo, pull_number):
        return [_changed_file()]

    def get_commit(self, owner, repo, sha):
        return (
            ReviewTargetInfo(
                source_type="commit",
                owner=owner,
                repo=repo,
                identifier=sha,
                title="Commit title",
                base_branch="parent",
                head_branch=sha,
                base_sha="parent-sha",
                head_sha=sha,
                author="alice",
                url=f"https://github.com/{owner}/{repo}/commit/{sha}",
            ),
            [_changed_file()],
        )

    def compare_commits(self, owner, repo, base_ref, head_ref):
        return (
            ReviewTargetInfo(
                source_type="compare",
                owner=owner,
                repo=repo,
                identifier=f"{base_ref}...{head_ref}",
                title="Compare title",
                base_branch=base_ref,
                head_branch=head_ref,
                base_sha="base-sha",
                head_sha="head-sha",
                author="",
                url=f"https://github.com/{owner}/{repo}/compare/{base_ref}...{head_ref}",
            ),
            [_changed_file()],
        )


def _changed_file():
    return ChangedFile(
        filename="src/app.py",
        status="modified",
        additions=1,
        deletions=1,
        changes=2,
        patch="@@ -1 +1 @@\n-old\n+new",
    )


def test_loader_supports_pull_request_target():
    change_set = ChangeSetLoader(FakeGitHubClient()).load("https://github.com/acme/app/pull/1")

    assert change_set.target.source_type == "pull_request"
    assert change_set.hunks_by_file["src/app.py"][0].new_start == 1


def test_loader_supports_commit_target():
    change_set = ChangeSetLoader(FakeGitHubClient()).load("https://github.com/acme/app/commit/abc123")

    assert change_set.target.source_type == "commit"
    assert change_set.target.identifier == "abc123"


def test_loader_supports_compare_target():
    change_set = ChangeSetLoader(FakeGitHubClient()).load("https://github.com/acme/app/compare/main...feature")

    assert change_set.target.source_type == "compare"
    assert change_set.target.identifier == "main...feature"


def test_loader_supports_local_diff_target(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=tmp_path, check=True)
    app_file = tmp_path / "app.py"
    app_file.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    app_file.write_text("new\n", encoding="utf-8")

    change_set = ChangeSetLoader(FakeGitHubClient(), repo_root=tmp_path).load("local")

    assert change_set.target.source_type == "local_diff"
    assert change_set.files[0].filename == "app.py"
    assert change_set.hunks_by_file["app.py"][0].lines[-1].content == "new"
