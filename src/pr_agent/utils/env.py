"""轻量 .env 加载器：避免为了 MVP 额外引入 python-dotenv 依赖。"""

from __future__ import annotations

import os
from pathlib import Path


def default_dotenv_path(start: str | Path | None = None) -> Path:
    anchor = Path(start) if start is not None else Path(__file__).resolve()
    search_from = anchor if anchor.is_dir() else anchor.parent

    for parent in (search_from, *search_from.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src" / "pr_agent").exists():
            return parent / ".env"

    return search_from / ".env"


def load_dotenv_file(path: str | Path | None = None) -> None:
    env_path = Path(path) if path is not None else default_dotenv_path()
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 不覆盖真实环境变量，方便 CI / GitHub Action 用 Secrets 注入。
        if key and key not in os.environ:
            os.environ[key] = value
