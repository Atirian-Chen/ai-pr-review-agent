"""GitHub REST Client：只读取 PR 和文件内容，不执行 PR 中的任何代码。"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote, urlparse

from pr_agent.github.models import (
    ChangedFile,
    PRInfo,
    PullRequestRef,
    changed_file_from_api,
    pr_info_from_api,
)


class GitHubAPIError(RuntimeError):
    """GitHub API 调用失败时抛出，保留状态码和响应摘要方便排查。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_github_pr_url(url: str) -> PullRequestRef:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError(f"Invalid GitHub PR URL: {url}")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "pull" or not re.fullmatch(r"\d+", parts[3]):
        raise ValueError(f"Invalid GitHub PR URL: {url}")

    return PullRequestRef(owner=parts[0], repo=parts[1], pull_number=int(parts[3]))


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self.api_base_url = api_base_url.rstrip("/")
        if client is not None:
            self._client = client
        else:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("httpx is required to call the GitHub API") from exc
            self._client = httpx.Client(timeout=timeout_seconds)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-pr-review-agent",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json(self, path: str, params: dict | None = None) -> dict | list:
        response = self._client.get(
            f"{self.api_base_url}{path}",
            headers=self._headers(),
            params=params,
        )
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API error {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        return response.json()

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> PRInfo:
        data = self._get_json(f"/repos/{owner}/{repo}/pulls/{pull_number}")
        if not isinstance(data, dict):
            raise GitHubAPIError("Unexpected pull request response shape")
        return pr_info_from_api(data, owner=owner, repo=repo)

    def list_pull_request_files(self, owner: str, repo: str, pull_number: int) -> list[ChangedFile]:
        files: list[ChangedFile] = []
        page = 1
        while True:
            data = self._get_json(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(data, list):
                raise GitHubAPIError("Unexpected changed files response shape")

            files.extend(changed_file_from_api(item) for item in data)
            if len(data) < 100:
                break
            page += 1
        return files

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        encoded_path = quote(path, safe="/")
        response = self._client.get(
            f"{self.api_base_url}/repos/{owner}/{repo}/contents/{encoded_path}",
            headers=self._headers(accept="application/vnd.github.raw"),
            params={"ref": ref},
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub content API error {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        return response.text
