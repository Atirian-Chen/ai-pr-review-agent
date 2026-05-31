from pr_agent.github.models import changed_file_from_api, pr_info_from_api


def test_pr_info_from_api():
    data = {
        "number": 7,
        "title": "Improve login",
        "body": "Body",
        "base": {"ref": "main", "sha": "base-sha"},
        "head": {"ref": "feature", "sha": "head-sha"},
        "user": {"login": "alice"},
        "html_url": "https://github.com/acme/app/pull/7",
    }

    pr = pr_info_from_api(data, owner="acme", repo="app")

    assert pr.owner == "acme"
    assert pr.repo == "app"
    assert pr.pull_number == 7
    assert pr.base_sha == "base-sha"
    assert pr.head_sha == "head-sha"


def test_changed_file_from_api():
    file = changed_file_from_api(
        {
            "filename": "src/app.py",
            "status": "modified",
            "additions": 2,
            "deletions": 1,
            "changes": 3,
            "patch": "@@ -1 +1 @@\n-old\n+new",
            "raw_url": "https://raw.example/src/app.py",
        }
    )

    assert file.filename == "src/app.py"
    assert file.status == "modified"
    assert file.changes == 3
    assert file.patch is not None
