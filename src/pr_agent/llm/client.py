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
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise LLMAPIError("OPENAI_API_KEY is required for review mode")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        if client is not None:
            self._client = client
        else:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("httpx is required to call an OpenAI-compatible LLM API") from exc
            self._client = httpx.Client(timeout=60.0)

    @classmethod
    def from_env(cls, settings: LLMSettings) -> "OpenAICompatibleLLMClient":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", settings.model),
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        start = time.perf_counter()
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        latency = time.perf_counter() - start
        if response.status_code >= 400:
            raise LLMAPIError(f"LLM API error {response.status_code}: {response.text[:500]}")

        body = response.json()
        raw_text = body["choices"][0]["message"]["content"]
        return LLMJsonResponse(
            data=parse_json_payload(raw_text),
            latency_seconds=latency,
            model=body.get("model") or self.model,
            usage=body.get("usage") or {},
            raw_text=raw_text,
        )
