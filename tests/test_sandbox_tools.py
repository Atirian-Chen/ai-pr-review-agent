import shutil

from pr_agent.review.schema import ToolKind
from pr_agent.tools.sandbox import SandboxCommandBuilder, SandboxExecutor


def test_pytest_command_builder_uses_allowlisted_template():
    command = SandboxCommandBuilder().build_pytest_command("tests/test_app.py", "test_app")

    assert command == ["python", "-m", "pytest", "-q", "tests/test_app.py::test_app"]


def test_ruff_and_mypy_command_builders_validate_paths():
    builder = SandboxCommandBuilder()

    assert builder.build_ruff_command(["src/app.py"]) == ["ruff", "check", "src/app.py"]
    assert builder.build_mypy_command(["src/app.py"]) == ["mypy", "src/app.py"]


def test_docker_args_disable_network_and_drop_capabilities(tmp_path):
    args = SandboxCommandBuilder().build_docker_args(tmp_path, ["python", "-m", "pytest", "-q", "tests/test_app.py"])

    assert "--network" in args
    assert "none" in args
    assert "--cap-drop" in args
    assert "ALL" in args
    assert "--security-opt" in args
    assert "no-new-privileges" in args
    assert "--read-only" in args


def test_docker_args_do_not_forward_secrets(tmp_path):
    args = SandboxCommandBuilder().build_docker_args(tmp_path, ["mypy", "src/app.py"])

    assert "OPENAI_API_KEY" not in args
    assert "GITHUB_TOKEN" not in args
    assert "VERIFIER_OPENAI_API_KEY" not in args
    assert "PYTHONDONTWRITEBYTECODE=1" in args


def test_sandbox_executor_skips_when_docker_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = SandboxExecutor().run_pytest(tmp_path, "tests/test_app.py", timeout_seconds=1)

    assert result.tool == ToolKind.PYTEST
    assert not result.success
    assert "Docker is not available" in result.summary


def test_pytest_command_builder_rejects_shell_syntax():
    builder = SandboxCommandBuilder()

    try:
        builder.build_pytest_command("tests/test_app.py; rm -rf /")
    except ValueError as exc:
        assert "Unsafe repository path" in str(exc) or "shell" in str(exc)
    else:
        raise AssertionError("unsafe pytest path should be rejected")
