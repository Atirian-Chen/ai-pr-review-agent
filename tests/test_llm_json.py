import pytest

from pr_agent.config import LLMSettings
from pr_agent.llm.client import LLMAPIError, LLMOutputError, OpenAICompatibleLLMClient, parse_json_payload


def test_parse_plain_json_payload():
    assert parse_json_payload('{"findings": []}') == {"findings": []}


def test_parse_fenced_json_payload():
    text = """```json
{"summary": "ok", "findings": []}
```"""

    assert parse_json_payload(text)["summary"] == "ok"


def test_parse_json_payload_with_extra_text():
    text = 'Here is the result: {"summary": "ok", "findings": []} Thanks.'

    assert parse_json_payload(text)["findings"] == []


def test_parse_invalid_json_payload_raises():
    with pytest.raises(LLMOutputError):
        parse_json_payload("no json here")


def test_from_env_uses_timeout_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "9.5")

    client = OpenAICompatibleLLMClient.from_env(LLMSettings(timeout_seconds=42.0))

    assert client.timeout_seconds == 9.5
    client._client.close()


def test_from_env_supports_verifier_prefix(monkeypatch):
    monkeypatch.setenv("VERIFIER_OPENAI_API_KEY", "verifier-key")
    monkeypatch.setenv("VERIFIER_OPENAI_BASE_URL", "https://verifier.example/v1")
    monkeypatch.setenv("VERIFIER_OPENAI_MODEL", "verifier-mini")
    monkeypatch.setenv("VERIFIER_OPENAI_TIMEOUT_SECONDS", "3.5")

    client = OpenAICompatibleLLMClient.from_env(LLMSettings(timeout_seconds=42.0), env_prefix="VERIFIER_OPENAI")

    assert client.api_key == "verifier-key"
    assert client.base_url == "https://verifier.example/v1"
    assert client.model == "verifier-mini"
    assert client.timeout_seconds == 3.5
    client._client.close()


def test_complete_json_wraps_httpx_timeout():
    import httpx

    class TimeoutClient:
        def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("slow")

    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1.0,
        client=TimeoutClient(),
    )

    with pytest.raises(LLMAPIError, match="timed out after 1.0 seconds"):
        client.complete_json("system", "user")


def test_complete_json_repairs_non_json_response():
    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, content):
            self._content = content

        def json(self):
            return {
                "model": "test-model",
                "choices": [{"message": {"content": self._content}}],
                "usage": {"total_tokens": 10},
            }

    class RepairClient:
        def __init__(self):
            self.payloads = []
            self.responses = [
                FakeResponse("No clear issue found."),
                FakeResponse('{"summary": "No clear issue found.", "findings": []}'),
            ]

        def post(self, *args, **kwargs):
            self.payloads.append(kwargs["json"])
            return self.responses.pop(0)

    fake_client = RepairClient()
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        client=fake_client,
    )

    response = client.complete_json("system", "user")

    assert response.data == {"summary": "No clear issue found.", "findings": []}
    assert response.usage["total_tokens"] == 20
    assert len(fake_client.payloads) == 2
    assert "previous model response was not valid JSON" in fake_client.payloads[1]["messages"][1]["content"]


def test_complete_json_reports_preview_when_repair_fails():
    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, content):
            self._content = content

        def json(self):
            return {
                "model": "test-model",
                "choices": [{"message": {"content": self._content}}],
                "usage": {},
            }

    class BadRepairClient:
        def __init__(self):
            self.responses = [FakeResponse("plain text only"), FakeResponse("still not json")]

        def post(self, *args, **kwargs):
            return self.responses.pop(0)

    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        client=BadRepairClient(),
    )

    with pytest.raises(LLMOutputError, match="Original output preview: plain text only"):
        client.complete_json("system", "user")
