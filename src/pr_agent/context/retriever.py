"""MVP 上下文检索：不做 embedding，优先提供 diff、同文件周边代码和 README 线索。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pr_agent.config import AppConfig
from pr_agent.context.models import ReviewContext
from pr_agent.diff.models import DiffHunk
from pr_agent.github.client import GitHubClient
from pr_agent.github.models import ChangedFile, ReviewTargetInfo


class ContextRetriever:
    def __init__(self, github_client: GitHubClient, config: AppConfig, repo_root: Path | None = None) -> None:
        self.github_client = github_client
        self.config = config
        self.repo_root = repo_root

    def build(self, pr: ReviewTargetInfo, changed_file: ChangedFile, hunks: list[DiffHunk]) -> ReviewContext:
        surrounding_code = self._get_surrounding_code(pr, changed_file, hunks)
        readme_excerpt = self._get_readme_excerpt(pr) if self.config.context.include_readme else None
        related_tests = infer_related_test_files(changed_file.filename) if self.config.context.include_related_tests else []

        return ReviewContext(
            pr=pr,
            file=changed_file,
            hunks=hunks,
            target_file_patch=changed_file.patch or "",
            surrounding_code=surrounding_code,
            related_test_files=related_tests,
            repo_readme_excerpt=readme_excerpt,
        )

    def _get_surrounding_code(self, pr: ReviewTargetInfo, changed_file: ChangedFile, hunks: list[DiffHunk]) -> str | None:
        if changed_file.status == "removed":
            return None

        if pr.source_type == "local_diff":
            content = self._get_local_file_content(changed_file.filename)
        else:
            content = self.github_client.get_file_content(
                owner=pr.owner,
                repo=pr.repo,
                path=changed_file.filename,
                ref=pr.head_sha,
            )
        if content is None:
            return None

        lines = content.splitlines()
        changed_lines = [
            line.new_line_no
            for hunk in hunks
            for line in hunk.lines
            if line.line_type == "add" and line.new_line_no is not None
        ]
        if not changed_lines:
            return _truncate(content, self.config.context.max_context_chars_per_file)

        # 只截取覆盖新增行的最小窗口，避免把整个文件塞进 prompt。
        radius = self.config.context.surrounding_lines
        start = max(min(changed_lines) - radius, 1)
        end = min(max(changed_lines) + radius, len(lines))
        numbered = [f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1)]
        return _truncate("\n".join(numbered), self.config.context.max_context_chars_per_file)

    def _get_readme_excerpt(self, pr: ReviewTargetInfo) -> str | None:
        if pr.source_type == "local_diff":
            content = self._get_local_file_content("README.md")
            return _truncate(content, self.config.context.readme_excerpt_chars) if content else None

        content = self.github_client.get_file_content(pr.owner, pr.repo, "README.md", pr.head_sha)
        if not content:
            return None
        return _truncate(content, self.config.context.readme_excerpt_chars)

    def _get_local_file_content(self, path: str) -> str | None:
        root = self.repo_root
        if root is None:
            return None
        file_path = root / path
        if not file_path.exists() or not file_path.is_file():
            return None
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="replace")


def _truncate(text: str, max_chars: int) -> str:
    # prompt 截断保留明确标记，方便排查上下文不足导致的 review 质量问题。
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def infer_related_test_files(path: str) -> list[str]:
    normalized = path.replace("\\", "/")
    file_path = PurePosixPath(normalized)
    stem = file_path.stem
    suffix = file_path.suffix
    without_src = normalized.removeprefix("src/")

    candidates: list[str] = []
    if suffix == ".py":
        candidates.extend(
            [
                f"tests/test_{stem}.py",
                f"tests/{without_src}",
                str(file_path.with_name(f"test_{file_path.name}")),
            ]
        )
    elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
        candidates.extend(
            [
                str(file_path.with_suffix(f".test{suffix}")),
                str(file_path.with_suffix(f".spec{suffix}")),
                f"tests/{stem}.test{suffix}",
            ]
        )
    elif suffix == ".java":
        candidates.extend([f"src/test/java/{stem}Test.java", f"tests/{stem}Test.java"])

    # 去重但保持顺序，报告里展示时更可读。
    return list(dict.fromkeys(candidates))
