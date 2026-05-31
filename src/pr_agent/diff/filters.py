"""文件过滤规则：MVP 阶段跳过低价值或高风险的大文件/生成文件。"""

from __future__ import annotations

from pathlib import PurePosixPath

from pr_agent.config import AppConfig
from pr_agent.github.models import ChangedFile


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def should_review_file(changed_file: ChangedFile, config: AppConfig) -> bool:
    filename = _normalize_path(changed_file.filename)
    lower_name = filename.lower()
    basename = PurePosixPath(filename).name.lower()

    if changed_file.status == "removed" or not changed_file.patch:
        return False

    if changed_file.changes > config.filters.max_patch_lines_per_file:
        return False

    for prefix in config.filters.skip_paths:
        if lower_name.startswith(_normalize_path(prefix).lower()):
            return False

    if basename in {name.lower() for name in config.filters.skip_files}:
        return False

    suffix = PurePosixPath(lower_name).suffix
    if suffix in {ext.lower() for ext in config.filters.skip_extensions}:
        return False

    if lower_name.endswith(".min.js"):
        return False

    return True
