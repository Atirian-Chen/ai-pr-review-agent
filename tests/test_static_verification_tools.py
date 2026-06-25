from pathlib import Path

from pr_agent.review.schema import ReviewFinding, ToolKind
from pr_agent.tools.dependency_inspection import inspect_dependencies
from pr_agent.tools.read_file import read_repository_file
from pr_agent.tools.repository_search import repository_search
from pr_agent.tools.test_discovery import discover_tests


def test_repository_search_finds_matches_and_writes_artifact(tmp_path):
    _write(tmp_path / "src/app.py", "def parse_config(value):\n    return value\n")

    result = repository_search(tmp_path, ["parse_config"], tmp_path / "artifacts")

    assert result.tool == ToolKind.REPOSITORY_SEARCH
    assert result.success
    assert result.matched_paths == ["src/app.py"]
    assert result.matched_lines == [1]
    assert result.artifact_path is not None
    assert Path(result.artifact_path).exists()


def test_repository_search_respects_result_limit(tmp_path):
    _write(tmp_path / "src/app.py", "\n".join("parse_config()" for _ in range(10)))

    result = repository_search(tmp_path, ["parse_config"], max_results=3)

    assert len(result.matched_lines) == 3
    assert result.output_truncated


def test_repository_search_skips_sensitive_files(tmp_path):
    _write(tmp_path / ".env", "TOKEN=parse_config\n")
    _write(tmp_path / "src/app.py", "def app():\n    pass\n")

    result = repository_search(tmp_path, ["TOKEN"])

    assert result.matched_paths == []


def test_read_file_refuses_sensitive_file(tmp_path):
    _write(tmp_path / ".env", "SECRET=1\n")

    result = read_repository_file(tmp_path, ".env")

    assert not result.success
    assert "Unsafe repository path" in result.summary


def test_test_discovery_finds_related_tests(tmp_path):
    _write(tmp_path / "src/foo/bar.py", "def load():\n    return 1\n")
    _write(tmp_path / "tests/foo/test_bar.py", "def test_load():\n    assert True\n")
    finding = _finding("src/foo/bar.py")

    result, candidates = discover_tests(tmp_path, finding)

    assert result.tool == ToolKind.TEST_DISCOVERY
    assert candidates == ["tests/foo/test_bar.py"]


def test_test_discovery_uses_test_suggestion_first(tmp_path):
    _write(tmp_path / "src/app.py", "def load():\n    return 1\n")
    _write(tmp_path / "tests/test_custom.py", "def test_custom():\n    assert True\n")
    finding = _finding(
        "src/app.py",
        test_suggestions=[
            {
                "test_file_path": "tests/test_custom.py",
                "test_name": "test_custom",
                "scenario": "custom",
            }
        ],
    )

    _, candidates = discover_tests(tmp_path, finding)

    assert candidates[0] == "tests/test_custom.py"


def test_dependency_inspection_detects_python_tools(tmp_path):
    _write(tmp_path / "pyproject.toml", '[project.optional-dependencies]\ndev = ["pytest", "ruff", "mypy"]\n')

    result = inspect_dependencies(tmp_path)

    assert result.success
    assert "pytest" in result.summary
    assert "pyproject.toml" in result.matched_paths


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _finding(path: str, **overrides) -> ReviewFinding:
    data = {
        "id": "F-1",
        "file_path": path,
        "line_start": 1,
        "line_end": 1,
        "category": "bug",
        "severity": "major",
        "confidence": 0.8,
        "title": "Possible bug",
        "description": "The changed branch can fail.",
        "evidence": "+ changed",
        "suggestion": "Guard the branch.",
        "reviewer": "bug",
    }
    data.update(overrides)
    return ReviewFinding.model_validate(data)
