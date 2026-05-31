"""轻量 .env 加载器：避免为了 MVP 额外引入 python-dotenv 依赖。"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
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
