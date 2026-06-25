import json

import pytest

from pr_agent.github.actions import GitHubActionSkip, resolve_action_review_target


def _write_event(tmp_path, payload):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_resolve_pull_request_event(tmp_path):
    path = _write_event(
        tmp_path,
        {
            "repository": {"full_name": "acme/app"},
            "pull_request": {"number": 7, "html_url": "https://github.com/acme/app/pull/7"},
        },
    )

    target = resolve_action_review_target(event_name="pull_request", event_path=path)

    assert target.target == "https://github.com/acme/app/pull/7"
    assert target.comment_target_type == "pull_request"
    assert target.pull_number == 7
    assert not target.is_fork_pull_request


def test_resolve_fork_pull_request_event_marks_fork(tmp_path):
    path = _write_event(
        tmp_path,
        {
            "repository": {"full_name": "acme/app"},
            "pull_request": {
                "number": 7,
                "html_url": "https://github.com/acme/app/pull/7",
                "head": {"repo": {"full_name": "contrib/app"}},
            },
        },
    )

    target = resolve_action_review_target(event_name="pull_request", event_path=path)

    assert target.is_fork_pull_request


def test_resolve_push_event_to_compare_target(tmp_path):
    before = "1" * 40
    after = "2" * 40
    path = _write_event(tmp_path, {"repository": {"full_name": "acme/app"}, "before": before, "after": after})

    target = resolve_action_review_target(event_name="push", event_path=path)

    assert target.target == f"https://github.com/acme/app/compare/{before}...{after}"
    assert target.comment_target_type == "commit"
    assert target.commit_sha == after


def test_resolve_branch_creation_push_to_commit_target(tmp_path):
    after = "2" * 40
    path = _write_event(tmp_path, {"repository": {"full_name": "acme/app"}, "before": "0" * 40, "after": after})

    target = resolve_action_review_target(event_name="push", event_path=path)

    assert target.target == f"https://github.com/acme/app/commit/{after}"
    assert target.commit_sha == after


def test_skips_branch_deletion_push(tmp_path):
    path = _write_event(tmp_path, {"repository": {"full_name": "acme/app"}, "before": "1" * 40, "after": "0" * 40})

    with pytest.raises(GitHubActionSkip):
        resolve_action_review_target(event_name="push", event_path=path)
