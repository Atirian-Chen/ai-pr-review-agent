from pr_agent.github.client import GitHubClient
from pr_agent.github.comments import SUMMARY_COMMENT_MARKER


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, get_payloads):
        self.get_payloads = list(get_payloads)
        self.posts = []
        self.patches = []

    def get(self, url, headers=None, params=None):
        return FakeResponse(payload=self.get_payloads.pop(0))

    def post(self, url, headers=None, json=None):
        self.posts.append((url, json))
        return FakeResponse(status_code=201, payload={"id": 101, "body": json["body"]})

    def patch(self, url, headers=None, json=None):
        self.patches.append((url, json))
        return FakeResponse(payload={"id": 100, "body": json["body"]})


def test_upsert_issue_comment_updates_existing_marker_comment():
    fake_http = FakeHttpClient([[{"id": 100, "body": f"{SUMMARY_COMMENT_MARKER}\nold"}]])
    client = GitHubClient(client=fake_http)

    response = client.upsert_issue_comment("acme", "app", 7, f"{SUMMARY_COMMENT_MARKER}\nnew", SUMMARY_COMMENT_MARKER)

    assert response["id"] == 100
    assert len(fake_http.patches) == 1
    assert "/repos/acme/app/issues/comments/100" in fake_http.patches[0][0]
    assert not fake_http.posts


def test_upsert_issue_comment_creates_when_marker_missing():
    fake_http = FakeHttpClient([[{"id": 100, "body": "someone else"}]])
    client = GitHubClient(client=fake_http)

    response = client.upsert_issue_comment("acme", "app", 7, f"{SUMMARY_COMMENT_MARKER}\nnew", SUMMARY_COMMENT_MARKER)

    assert response["id"] == 101
    assert len(fake_http.posts) == 1
    assert "/repos/acme/app/issues/7/comments" in fake_http.posts[0][0]
    assert not fake_http.patches


def test_create_commit_comment_posts_to_commit_endpoint():
    fake_http = FakeHttpClient([])
    client = GitHubClient(client=fake_http)

    response = client.create_commit_comment("acme", "app", "abc123", "body")

    assert response["id"] == 101
    assert len(fake_http.posts) == 1
    assert "/repos/acme/app/commits/abc123/comments" in fake_http.posts[0][0]
