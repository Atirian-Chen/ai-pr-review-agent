"""Diff 数据模型：保留新旧行号，后续用于行号校验和 GitHub 评论定位。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DiffLine(BaseModel):
    line_type: Literal["add", "delete", "context"]
    content: str
    old_line_no: int | None
    new_line_no: int | None


class DiffHunk(BaseModel):
    filename: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section_header: str | None
    lines: list[DiffLine]
