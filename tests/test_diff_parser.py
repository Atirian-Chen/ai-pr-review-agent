from pr_agent.diff.parser import parse_patch


def test_parse_patch_with_add_delete_and_context_lines():
    patch = """@@ -1,3 +1,4 @@ def foo():
 unchanged
-old
+new
 tail
+extra"""

    hunks = parse_patch("src/app.py", patch)

    assert len(hunks) == 1
    assert hunks[0].old_start == 1
    assert hunks[0].new_start == 1
    assert hunks[0].section_header == "def foo():"
    assert [line.line_type for line in hunks[0].lines] == ["context", "delete", "add", "context", "add"]
    assert hunks[0].lines[1].old_line_no == 2
    assert hunks[0].lines[1].new_line_no is None
    assert hunks[0].lines[2].new_line_no == 2


def test_parse_patch_with_multiple_hunks():
    patch = """@@ -1 +1 @@
-a
+b
@@ -10,2 +10,2 @@ class App
 context
-x
+y"""

    hunks = parse_patch("src/app.py", patch)

    assert len(hunks) == 2
    assert hunks[1].old_start == 10
    assert hunks[1].section_header == "class App"
    assert hunks[1].lines[-1].new_line_no == 11
