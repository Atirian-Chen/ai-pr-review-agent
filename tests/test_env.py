import os

import pr_agent.utils.env as env_module
from pr_agent.utils.env import default_dotenv_path, load_dotenv_file


def test_load_dotenv_file_sets_missing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=test-model\nEMPTY=\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    load_dotenv_file(env_file)

    assert os.environ["OPENAI_MODEL"] == "test-model"
    assert os.environ["EMPTY"] == ""


def test_load_dotenv_file_does_not_override_existing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_MODEL", "shell-model")

    load_dotenv_file(env_file)

    assert os.environ["OPENAI_MODEL"] == "shell-model"


def test_default_dotenv_path_uses_agent_root_not_current_directory(tmp_path, monkeypatch):
    agent_root = tmp_path / "cr-agent"
    utils_dir = agent_root / "src" / "pr_agent" / "utils"
    caller_repo = tmp_path / "caller-repo"
    utils_dir.mkdir(parents=True)
    caller_repo.mkdir()
    (agent_root / "pyproject.toml").write_text("[project]\nname = 'cr-agent'\n", encoding="utf-8")
    (agent_root / ".env").write_text("OPENAI_MODEL=agent-model\n", encoding="utf-8")
    (caller_repo / ".env").write_text("OPENAI_MODEL=caller-model\n", encoding="utf-8")

    monkeypatch.chdir(caller_repo)

    assert default_dotenv_path(utils_dir / "env.py") == agent_root / ".env"


def test_load_dotenv_file_default_uses_agent_root_not_current_directory(tmp_path, monkeypatch):
    agent_root = tmp_path / "cr-agent"
    utils_dir = agent_root / "src" / "pr_agent" / "utils"
    caller_repo = tmp_path / "caller-repo"
    utils_dir.mkdir(parents=True)
    caller_repo.mkdir()
    (agent_root / "pyproject.toml").write_text("[project]\nname = 'cr-agent'\n", encoding="utf-8")
    (agent_root / ".env").write_text("OPENAI_MODEL=agent-model\n", encoding="utf-8")
    (caller_repo / ".env").write_text("OPENAI_MODEL=caller-model\n", encoding="utf-8")
    monkeypatch.setattr(env_module, "__file__", str(utils_dir / "env.py"))
    monkeypatch.chdir(caller_repo)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    load_dotenv_file()

    assert os.environ["OPENAI_MODEL"] == "agent-model"
