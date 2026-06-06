"""完整 unified diff parser：用于把本地 `git diff` 拆成文件级 patch。"""

from __future__ import annotations

from pr_agent.github.models import ChangedFile


def parse_full_unified_diff(diff_text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current: _FilePatch | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current.to_changed_file())
            current = _FilePatch.from_diff_git_line(line)
            continue

        if current is None:
            continue

        if line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "removed"
        elif line.startswith("rename from "):
            current.previous_filename = line.removeprefix("rename from ").strip()
            current.status = "renamed"
        elif line.startswith("rename to "):
            current.filename = line.removeprefix("rename to ").strip()
        elif line.startswith("+++ "):
            parsed = _strip_diff_path(line.removeprefix("+++ ").strip())
            if parsed != "/dev/null":
                current.filename = parsed
        elif line.startswith("@@ "):
            current.patch_lines.append(line)
        elif current.patch_lines:
            current.patch_lines.append(line)

    if current is not None:
        files.append(current.to_changed_file())

    return [file for file in files if file.patch]


class _FilePatch:
    def __init__(self, filename: str, previous_filename: str | None = None) -> None:
        self.filename = filename
        self.previous_filename = previous_filename
        self.status = "modified"
        self.patch_lines: list[str] = []

    @classmethod
    def from_diff_git_line(cls, line: str) -> "_FilePatch":
        # 形如：diff --git a/src/app.py b/src/app.py
        parts = line.split()
        new_path = _strip_diff_path(parts[3]) if len(parts) >= 4 else ""
        old_path = _strip_diff_path(parts[2]) if len(parts) >= 3 else None
        return cls(filename=new_path, previous_filename=old_path if old_path != new_path else None)

    def to_changed_file(self) -> ChangedFile:
        additions = 0
        deletions = 0
        for line in self.patch_lines:
            if line.startswith("@@ ") or line.startswith("\\"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1

        return ChangedFile(
            filename=self.filename,
            status=self.status,  # type: ignore[arg-type]
            additions=additions,
            deletions=deletions,
            changes=additions + deletions,
            patch="\n".join(self.patch_lines),
            previous_filename=self.previous_filename,
        )


def _strip_diff_path(path: str) -> str:
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
