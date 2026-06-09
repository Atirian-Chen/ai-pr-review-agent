"""OpenAI-compatible LLM client：负责 JSON 调用、JSON 修复和用量统计。"""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pr_agent.config import LLMSettings


class LLMOutputError(RuntimeError):
    pass


class LLMAPIError(RuntimeError):
    pass


@dataclass
class LLMJsonResponse:
    data: dict[str, Any]
    latency_seconds: float
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


class LLMClient(ABC):
    @abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        raise NotImplementedError


def parse_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Invalid fenced JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed

    # 一些模型会在 JSON 前后加解释文字；这里尝试截取最外层对象。
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        try:
            parsed = json.loads(stripped[first : last + 1])
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Invalid JSON object in model output: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed

    raise LLMOutputError("Model output does not contain a valid JSON object")


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.1,
        max_output_tokens: int = 3000,
        timeout_seconds: float = 120.0,
        client: Any | None = None,
        api_key_name: str = "OPENAI_API_KEY",
    ) -> None:
        if not api_key:
            raise LLMAPIError(f"{api_key_name} is required for review mode")
        self.timeout_env_name = api_key_name.removesuffix("_API_KEY") + "_TIMEOUT_SECONDS"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        if client is not None:
            self._client = client
        else:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("httpx is required to call an OpenAI-compatible LLM API") from exc
            self._client = httpx.Client(timeout=timeout_seconds)

    @classmethod
    def from_env(cls, settings: LLMSettings, env_prefix: str = "OPENAI") -> "OpenAICompatibleLLMClient":
        api_key_name = f"{env_prefix}_API_KEY"
        base_url_name = f"{env_prefix}_BASE_URL"
        model_name = f"{env_prefix}_MODEL"
        timeout_name = f"{env_prefix}_TIMEOUT_SECONDS"
        return cls(
            api_key=os.getenv(api_key_name, ""),
            base_url=os.getenv(base_url_name, "https://api.openai.com/v1"),
            model=os.getenv(model_name, settings.model),
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
            timeout_seconds=_env_float(timeout_name, settings.timeout_seconds),
            api_key_name=api_key_name,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        start = time.perf_counter()
        body = self._post_chat_completion(self._build_payload(system_prompt, user_prompt))
        raw_text = _extract_message_content(body)
        try:
            data = parse_json_payload(raw_text)
            output_text = raw_text
            usage = body.get("usage") or {}
            model = body.get("model") or self.model
        except LLMOutputError:
            repair_body = self._post_chat_completion(self._build_repair_payload(raw_text))
            repair_text = _extract_message_content(repair_body)
            try:
                data = parse_json_payload(repair_text)
            except LLMOutputError as repair_error:
                preview = _preview_text(raw_text)
                raise LLMOutputError(
                    "Model output was not valid JSON, and JSON repair also failed. "
                    f"Original output preview: {preview}"
                ) from repair_error
            output_text = f"{raw_text}\n\n[json_repair]\n{repair_text}"
            usage = _merge_usage(body.get("usage") or {}, repair_body.get("usage") or {})
            model = repair_body.get("model") or body.get("model") or self.model
        latency = time.perf_counter() - start
        return LLMJsonResponse(
            data=data,
            latency_seconds=latency,
            model=model,
            usage=usage,
            raw_text=output_text,
        )

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
        }

    def _build_repair_payload(self, raw_text: str) -> dict[str, Any]:
        system_prompt = (
            "You convert code review model output into valid JSON. "
            "Return JSON only. If the prior output reports no clear issue, "
            'return {"summary": "No clear issue found.", "findings": []}.'
        )
        user_prompt = (
            "The previous model response was not valid JSON. Convert it to this exact shape:\n"
            '{"summary": "short summary", "findings": []}\n\n'
            "Rules:\n"
            "- Preserve supported findings if they are present.\n"
            "- Use an empty findings array if there are no actionable findings.\n"
            "- Do not add markdown or explanatory text.\n\n"
            f"Previous response:\n{raw_text}"
        )
        return self._build_payload(system_prompt, user_prompt)

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        except Exception as exc:
            if exc.__class__.__module__.startswith("httpx") and "Timeout" in exc.__class__.__name__:
                raise LLMAPIError(
                    f"LLM API request timed out after {self.timeout_seconds} seconds. "
                    f"Increase {self.timeout_env_name} or the matching config timeout_seconds and retry."
                ) from exc
            raise
        if response.status_code >= 400:
            raise LLMAPIError(f"LLM API error {response.status_code}: {response.text[:500]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMAPIError(f"LLM API returned non-JSON response: {response.text[:500]}") from exc
        if not isinstance(body, dict):
            raise LLMAPIError("LLM API returned a non-object JSON response")
        return body


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMAPIError(f"{name} must be a number, got {raw!r}") from exc


def _extract_message_content(body: dict[str, Any]) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMAPIError("LLM API response did not include choices[0].message.content") from exc
    return "" if content is None else str(content)


def _merge_usage(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] += value
        elif key not in merged:
            merged[key] = value
    return merged


def _preview_text(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "<empty>"
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
