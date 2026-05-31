"""Unified diff parser：把 GitHub patch 文本解析成带行号的 hunk 结构。"""

from __future__ import annotations

import re

from pr_agent.diff.models import DiffHunk, DiffLine


HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: (?P<section>.*))?$"
)


def parse_patch(filename: str, patch: str | None) -> list[DiffHunk]:
    if not patch:
        return []

    hunks: list[DiffHunk] = []
    current: DiffHunk | None = None
    old_line_no = 0
    new_line_no = 0

    for raw_line in patch.splitlines():
        header_match = HUNK_HEADER_RE.match(raw_line)
        if header_match:
            if current is not None:
                hunks.append(current)

            old_start = int(header_match.group("old_start"))
            new_start = int(header_match.group("new_start"))
            current = DiffHunk(
                filename=filename,
                old_start=old_start,
                old_count=int(header_match.group("old_count") or 1),
                new_start=new_start,
                new_count=int(header_match.group("new_count") or 1),
                section_header=header_match.group("section"),
                lines=[],
            )
            old_line_no = old_start
            new_line_no = new_start
            continue

        if current is None or raw_line.startswith("\\"):
            continue

        # unified diff 的首字符决定该行是否消耗 old/new 行号。
        # 这里显式推进计数器，后续 validator 才能检查模型给出的 line_start 是否真实存在。
        prefix = raw_line[:1]
        content = raw_line[1:] if prefix in {"+", "-", " "} else raw_line
        if prefix == "+":
            current.lines.append(
                DiffLine(line_type="add", content=content, old_line_no=None, new_line_no=new_line_no)
            )
            new_line_no += 1
        elif prefix == "-":
            current.lines.append(
                DiffLine(line_type="delete", content=content, old_line_no=old_line_no, new_line_no=None)
            )
            old_line_no += 1
        else:
            current.lines.append(
                DiffLine(line_type="context", content=content, old_line_no=old_line_no, new_line_no=new_line_no)
            )
            old_line_no += 1
            new_line_no += 1

    if current is not None:
        hunks.append(current)
    return hunks
