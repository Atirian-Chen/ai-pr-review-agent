import pytest

from pr_agent.github.client import parse_github_pr_url


def test_parse_github_pr_url():
    ref = parse_github_pr_url("https://github.com/openai/example/pull/123")

    assert ref.owner == "openai"
    assert ref.repo == "example"
    assert ref.pull_number == 123


def test_parse_github_pr_url_with_trailing_slash():
    ref = parse_github_pr_url("https://github.com/openai/example/pull/123/")

    assert ref.pull_number == 123


def test_parse_github_pr_url_rejects_invalid_url():
    with pytest.raises(ValueError):
        parse_github_pr_url("https://github.com/openai/example/issues/123")
