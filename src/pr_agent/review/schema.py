"""结构化 review schema：所有模型输出都必须落到这些可校验字段。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pr_agent.github.models import ReviewTargetInfo


Category = Literal["bug", "security", "performance", "maintainability", "test", "style"]
Severity = Literal["critical", "major", "minor", "nit"]


class PatchSuggestion(BaseModel):
    description: str
    suggested_patch: str | None = None
    commands: list[str] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()


class TestSuggestion(BaseModel):
    test_file_path: str | None = None
    test_name: str
    scenario: str
    assertions: list[str] = Field(default_factory=list)
    suggested_test_code: str | None = None

    @field_validator("test_name", "scenario")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()


class ReviewFinding(BaseModel):
    id: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    description: str
    evidence: str
    suggestion: str
    suggested_patch: str | None = None
    failure_mode: str | None = None
    why_introduced_by_diff: str | None = None
    false_positive_checks: list[str] = Field(default_factory=list)
    patch_suggestion: PatchSuggestion | None = None
    test_suggestions: list[TestSuggestion] = Field(default_factory=list)
    reviewer: str

    @field_validator("title", "description", "evidence", "suggestion")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _line_range_is_valid(self) -> "ReviewFinding":
        if self.line_start is not None and self.line_start <= 0:
            raise ValueError("line_start must be positive")
        if self.line_end is not None and self.line_end <= 0:
            raise ValueError("line_end must be positive")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ReviewResult(BaseModel):
    pr: ReviewTargetInfo
    summary: str
    findings: list[ReviewFinding]
    stats: dict[str, Any] = Field(default_factory=dict)
    model_info: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
