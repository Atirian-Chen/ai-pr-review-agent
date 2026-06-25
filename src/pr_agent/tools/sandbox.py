"""Docker sandbox command builder and executor for approved verification checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from pr_agent.review.schema import ToolKind, ToolResult
from pr_agent.tools.base import contains_shell_syntax, should_skip_path, truncate_text
from pr_agent.tools.policy import validate_execution_path


DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
MAX_LOG_CHARS = 12000


class SandboxCommandBuilder:
    def __init__(self, image: str = DEFAULT_DOCKER_IMAGE) -> None:
        self.image = image

    def build_pytest_command(self, approved_test_path: str, approved_test_name: str | None = None) -> list[str]:
        path = validate_execution_path(approved_test_path)
        if approved_test_name:
            if contains_shell_syntax(approved_test_name) or "/" in approved_test_name or "\\" in approved_test_name:
                raise ValueError("pytest test name must be a simple pytest node id suffix")
            path = f"{path}::{approved_test_name}"
        return ["python", "-m", "pytest", "-q", path]

    def build_ruff_command(self, approved_paths: list[str]) -> list[str]:
        paths = [validate_execution_path(path) for path in approved_paths]
        if not paths:
            raise ValueError("ruff requires at least one approved path")
        return ["ruff", "check", *paths]

    def build_mypy_command(self, approved_paths: list[str]) -> list[str]:
        paths = [validate_execution_path(path) for path in approved_paths]
        if not paths:
            raise ValueError("mypy requires at least one approved path")
        return ["mypy", *paths]

    def build_docker_args(self, workspace_copy: Path, command: list[str]) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--cpus",
            "1.0",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "HOME=/tmp",
            "--workdir",
            "/workspace",
            "-v",
            f"{workspace_copy.resolve()}:/workspace:ro",
            self.image,
            *command,
        ]


class SandboxExecutor:
    def __init__(self, builder: SandboxCommandBuilder | None = None) -> None:
        self.builder = builder or SandboxCommandBuilder()

    def run_pytest(
        self,
        repo_root: Path,
        test_path: str,
        timeout_seconds: int,
        artifact_dir: Path | None = None,
    ) -> ToolResult:
        return self._run(
            ToolKind.PYTEST,
            repo_root,
            self.builder.build_pytest_command(test_path),
            timeout_seconds,
            artifact_dir,
            "pytest.log",
            [test_path],
        )

    def run_ruff(
        self,
        repo_root: Path,
        paths: list[str],
        timeout_seconds: int,
        artifact_dir: Path | None = None,
    ) -> ToolResult:
        return self._run(
            ToolKind.RUFF,
            repo_root,
            self.builder.build_ruff_command(paths),
            timeout_seconds,
            artifact_dir,
            "ruff.log",
            paths,
        )

    def run_mypy(
        self,
        repo_root: Path,
        paths: list[str],
        timeout_seconds: int,
        artifact_dir: Path | None = None,
    ) -> ToolResult:
        return self._run(
            ToolKind.MYPY,
            repo_root,
            self.builder.build_mypy_command(paths),
            timeout_seconds,
            artifact_dir,
            "mypy.log",
            paths,
        )

    def _run(
        self,
        tool: ToolKind,
        repo_root: Path,
        command: list[str],
        timeout_seconds: int,
        artifact_dir: Path | None,
        log_name: str,
        matched_paths: list[str],
    ) -> ToolResult:
        started = time.perf_counter()
        if shutil.which("docker") is None:
            return ToolResult(
                tool=tool,
                success=False,
                summary="Docker is not available; sandbox tool was skipped.",
                duration_ms=_duration_ms(started),
                matched_paths=matched_paths,
            )

        with tempfile.TemporaryDirectory(prefix="pr-agent-sandbox-") as tmp_dir:
            workspace_copy = Path(tmp_dir) / "workspace"
            _copy_workspace(repo_root, workspace_copy)
            docker_args = self.builder.build_docker_args(workspace_copy, command)
            try:
                completed = subprocess.run(
                    docker_args,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                )
                output = (completed.stdout or "") + (completed.stderr or "")
                log_text, truncated = truncate_text(output, MAX_LOG_CHARS)
                artifact_path = _write_log(artifact_dir, log_name, log_text)
                summary = _summary_for(tool, completed.returncode, command)
                return ToolResult(
                    tool=tool,
                    success=True,
                    exit_code=completed.returncode,
                    summary=summary,
                    duration_ms=_duration_ms(started),
                    artifact_path=artifact_path,
                    matched_paths=matched_paths,
                    output_truncated=truncated,
                )
            except subprocess.TimeoutExpired:
                artifact_path = _write_log(artifact_dir, log_name, f"Timed out after {timeout_seconds} seconds.")
                return ToolResult(
                    tool=tool,
                    success=False,
                    summary=f"{tool.value} timed out after {timeout_seconds} seconds.",
                    duration_ms=_duration_ms(started),
                    artifact_path=artifact_path,
                    matched_paths=matched_paths,
                )


def docker_is_available() -> bool:
    return shutil.which("docker") is not None


def _copy_workspace(src: Path, dst: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set()
        for name in names:
            candidate = Path(directory) / name
            try:
                relative = candidate.relative_to(src).as_posix()
            except ValueError:
                relative = name
            if should_skip_path(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(src, dst, ignore=ignore)


def _write_log(artifact_dir: Path | None, log_name: str, content: str) -> str | None:
    if artifact_dir is None:
        return None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / log_name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _summary_for(tool: ToolKind, exit_code: int, command: list[str]) -> str:
    command_label = " ".join(command)
    if exit_code == 0:
        return f"{tool.value} completed successfully: {command_label}"
    return f"{tool.value} completed with exit code {exit_code}: {command_label}"


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
