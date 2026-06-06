from pr_agent.diff.full_parser import parse_full_unified_diff


def test_parse_full_unified_diff_for_modified_file():
    diff_text = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 old
-bad
+good
+extra"""

    files = parse_full_unified_diff(diff_text)

    assert len(files) == 1
    assert files[0].filename == "src/app.py"
    assert files[0].status == "modified"
    assert files[0].additions == 2
    assert files[0].deletions == 1
    assert files[0].patch.startswith("@@ -1,2 +1,3 @@")


def test_parse_full_unified_diff_for_added_file():
    diff_text = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world"""

    files = parse_full_unified_diff(diff_text)

    assert files[0].filename == "new.txt"
    assert files[0].status == "added"
    assert files[0].additions == 2
    assert files[0].deletions == 0
