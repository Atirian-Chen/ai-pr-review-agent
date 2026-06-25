"""结构化 review schema：所有模型输出都必须落到这些可校验字段。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pr_agent.github.models import ReviewTargetInfo


Category = Literal["bug", "security", "performance", "maintainability", "test", "style"]
Severity = Literal["critical", "major", "minor", "nit"]


class ToolKind(str, Enum):
    REPOSITORY_SEARCH = "repository_search"
    READ_FILE = "read_file"
    TEST_DISCOVERY = "test_discovery"
    PYTEST = "pytest"
    RUFF = "ruff"
    MYPY = "mypy"
    DEPENDENCY_INSPECTION = "dependency_inspection"


class VerificationStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    NOT_ELIGIBLE = "not_eligible"
    SKIPPED = "skipped"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class VerificationIntent(BaseModel):
    needs_verification: bool = True
    preferred_tools: list[ToolKind] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    candidate_test_file: str | None = None

    @field_validator("search_terms")
    @classmethod
    def _clean_search_terms(cls, value: list[str]) -> list[str]:
        return [term.strip() for term in value if term and term.strip()]


class VerificationPlan(BaseModel):
    finding_id: str
    goal: str
    requested_tools: list[ToolKind]
    search_terms: list[str] = Field(default_factory=list)
    candidate_test_paths: list[str] = Field(default_factory=list)
    rationale: str
    risk_level: Literal["low", "medium", "high"]

    @field_validator("finding_id", "goal", "rationale")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()

    @field_validator("requested_tools")
    @classmethod
    def _tools_not_empty(cls, value: list[ToolKind]) -> list[ToolKind]:
        if not value:
            raise ValueError("requested_tools must not be empty")
        return list(dict.fromkeys(value))

    @field_validator("search_terms", "candidate_test_paths")
    @classmethod
    def _clean_string_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class ToolResult(BaseModel):
    tool: ToolKind
    success: bool
    summary: str
    exit_code: int | None = None
    duration_ms: int
    artifact_path: str | None = None
    matched_paths: list[str] = Field(default_factory=list)
    matched_lines: list[int] = Field(default_factory=list)
    output_truncated: bool = False

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()


class FindingVerification(BaseModel):
    status: VerificationStatus
    plan: VerificationPlan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_summary: str
    confidence_before: float = Field(ge=0.0, le=1.0)
    confidence_after: float = Field(ge=0.0, le=1.0)
    publication_decision: Literal["publish", "publish_with_warning", "suppress"]

    @field_validator("evidence_summary")
    @classmethod
    def _evidence_summary_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()


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
    verification_intent: VerificationIntent | None = None
    verification: FindingVerification | None = None
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
