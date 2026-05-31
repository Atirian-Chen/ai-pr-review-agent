import pytest

from pr_agent.llm.client import LLMOutputError, parse_json_payload


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
