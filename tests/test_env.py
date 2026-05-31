import os

from pr_agent.utils.env import load_dotenv_file


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
