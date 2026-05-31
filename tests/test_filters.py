from pr_agent.config import AppConfig
from pr_agent.diff.filters import should_review_file
from pr_agent.github.models import ChangedFile


def make_file(filename: str, changes: int = 2, patch: str | None = "@@ -1 +1 @@\n-a\n+b") -> ChangedFile:
    return ChangedFile(
        filename=filename,
        status="modified",
        additions=1,
        deletions=1,
        changes=changes,
        patch=patch,
    )


def test_should_review_normal_source_file():
    assert should_review_file(make_file("src/app.py"), AppConfig())


def test_should_skip_lock_file():
    assert not should_review_file(make_file("package-lock.json"), AppConfig())


def test_should_skip_binary_extension():
    assert not should_review_file(make_file("assets/logo.png"), AppConfig())


def test_should_skip_large_patch():
    assert not should_review_file(make_file("src/app.py", changes=1001), AppConfig())


def test_should_skip_file_without_patch():
    assert not should_review_file(make_file("src/app.py", patch=None), AppConfig())
