import pytest

from pr_agent.targets.parser import parse_review_target


def test_parse_pull_request_target():
    target = parse_review_target("https://github.com/acme/app/pull/12")

    assert target.source_type == "pull_request"
    assert target.owner == "acme"
    assert target.repo == "app"
    assert target.pull_number == 12


def test_parse_commit_target():
    target = parse_review_target("https://github.com/acme/app/commit/abc123")

    assert target.source_type == "commit"
    assert target.commit_sha == "abc123"


def test_parse_compare_target():
    target = parse_review_target("https://github.com/acme/app/compare/main...feature/review")

    assert target.source_type == "compare"
    assert target.base_ref == "main"
    assert target.head_ref == "feature/review"


def test_parse_local_target():
    target = parse_review_target("local")

    assert target.source_type == "local_diff"


def test_parse_unsupported_target():
    with pytest.raises(ValueError):
        parse_review_target("https://example.com/acme/app/pull/1")
