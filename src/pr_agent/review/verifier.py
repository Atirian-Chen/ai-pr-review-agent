"""Post-generation verification for review findings.

The LLM is treated as a candidate generator. This module applies deterministic
checks before a finding is published, focusing on common false-positive classes
that can be disproved from repository state, schemas, or command definitions.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from pr_agent.context.retriever import infer_related_test_files
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.targets.models import ChangeSet


SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "nit": 3}
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".venv-win",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
}

ABSOLUTE_TEST_GAP_RE = re.compile(
    r"("
    r"\b(no|without|lacks?|lack of|absence of)\b.{0,80}\b(tests?|unit tests?|coverage)\b"
    r"|\b(no|missing)\s+unit\s+tests?\b"
    r"|\bno\s+tests?\s+(were\s+)?(added|included|provided)\b"
    r"|\bunit\s+tests?\s+(were\s+)?not\s+(added|included|provided)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
NONE_CLAIM_RE = re.compile(r"\b(attributeerror|none|null|optional)\b", re.IGNORECASE)
ATTR_REF_RE = re.compile(r"\b([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\b")
COMMAND_CLAIM_RE = re.compile(r"\b(command|cli|dry-run|dry run)\b", re.IGNORECASE)
COMMAND_PROBLEM_RE = re.compile(r"\b(wrong|incorrect|invalid|missing|absent|not exist|does not exist|unknown)\b", re.IGNORECASE)
PR_AGENT_COMMAND_RE = re.compile(r"\bpr-agent\s+([a-zA-Z0-9_-]+)\b")
BACKTICK_COMMAND_RE = re.compile(r"`([a-zA-Z][a-zA-Z0-9_-]+)`")


@dataclass(frozen=True)
class SuppressedFinding:
    finding_id: str
    rule: str
    reason: str
    file_path: str
    title: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def verify_findings(
    result: ReviewResult,
    change_set: ChangeSet,
    repo_root: Path,
    max_findings: int,
) -> ReviewResult:
    """Suppress disproved findings, calibrate severity, and record audit stats."""

    evidence = RepositoryEvidence(repo_root=repo_root, change_set=change_set)
    suppressed: list[SuppressedFinding] = []
    verified: list[ReviewFinding] = []

    for finding in result.findings:
        suppression = _suppression_for(finding, evidence)
        if suppression is not None:
            suppressed.append(suppression)
            continue
        verified.append(_calibrate_finding(finding))

    verified.sort(key=lambda item: (SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_start or 0))
    published = verified[:max_findings]

    stats = dict(result.stats)
    stats["verification"] = {
        "candidate_findings": len(result.findings),
        "verified_findings": len(verified),
        "deterministic_verified_findings": len(verified),
        "deterministic_suppressed_findings": len(suppressed),
        "published_findings": len(published),
        "suppressed_findings": len(suppressed),
        "suppressions": [item.as_dict() for item in suppressed],
    }
    return result.model_copy(update={"findings": published, "stats": stats})


def _suppression_for(finding: ReviewFinding, evidence: "RepositoryEvidence") -> SuppressedFinding | None:
    test_reason = _missing_tests_contradicted(finding, evidence)
    if test_reason:
        return _suppressed(finding, "related-tests-exist", test_reason)

    none_reason = _non_optional_field_contradiction(finding, evidence)
    if none_reason:
        return _suppressed(finding, "non-optional-field", none_reason)

    command_reason = _existing_cli_command_contradiction(finding, evidence)
    if command_reason:
        return _suppressed(finding, "cli-command-exists", command_reason)

    return None


def _suppressed(finding: ReviewFinding, rule: str, reason: str) -> SuppressedFinding:
    return SuppressedFinding(
        finding_id=finding.id,
        rule=rule,
        reason=reason,
        file_path=finding.file_path,
        title=finding.title,
    )


def _missing_tests_contradicted(finding: ReviewFinding, evidence: "RepositoryEvidence") -> str | None:
    if finding.category != "test" and "test" not in _finding_text(finding).lower():
        return None
    if not ABSOLUTE_TEST_GAP_RE.search(_finding_text(finding)):
        return None
    related_tests = evidence.related_test_paths(finding.file_path)
    if not related_tests:
        return None
    changed_related = sorted(path for path in related_tests if path in evidence.changed_paths)
    if changed_related:
        return f"Related test file(s) changed in this review: {', '.join(changed_related[:5])}."
    return f"Related test file(s) already exist: {', '.join(sorted(related_tests)[:5])}."


def _non_optional_field_contradiction(finding: ReviewFinding, evidence: "RepositoryEvidence") -> str | None:
    text = _finding_text(finding)
    if not NONE_CLAIM_RE.search(text):
        return None

    for variable_name, field_name in ATTR_REF_RE.findall(text):
        if evidence.field_is_known_non_optional(finding.file_path, variable_name, field_name):
            return f"`{variable_name}.{field_name}` is defined as a non-optional field in the annotated model."
    return None


def _existing_cli_command_contradiction(finding: ReviewFinding, evidence: "RepositoryEvidence") -> str | None:
    text = _finding_text(finding)
    if not COMMAND_CLAIM_RE.search(text) or not COMMAND_PROBLEM_RE.search(text):
        return None

    commands = _extract_referenced_commands(text)
    if not commands:
        return None
    defined = evidence.defined_cli_commands()
    existing = sorted(command for command in commands if command in defined)
    if existing and len(existing) == len(commands):
        return f"Referenced CLI command(s) are defined: {', '.join(existing)}."
    return None


def _calibrate_finding(finding: ReviewFinding) -> ReviewFinding:
    if finding.category == "test" and finding.severity == "critical":
        return finding.model_copy(update={"severity": "major", "confidence": min(finding.confidence, 0.9)})
    path = PurePosixPath(finding.file_path.replace("\\", "/"))
    if _is_docs_path(str(path)) and finding.category != "security" and finding.severity in {"critical", "major"}:
        return finding.model_copy(update={"category": "maintainability", "severity": "minor", "confidence": min(finding.confidence, 0.8)})
    if _is_test_or_eval_path(str(path)) and finding.category != "security" and finding.severity in {"critical", "major"}:
        return finding.model_copy(update={"severity": "minor", "confidence": min(finding.confidence, 0.8)})
    return finding


def _finding_text(finding: ReviewFinding) -> str:
    parts = [
        finding.title,
        finding.description,
        finding.evidence,
        finding.suggestion,
        finding.failure_mode or "",
        finding.why_introduced_by_diff or "",
        " ".join(finding.false_positive_checks),
    ]
    return "\n".join(parts)


def _extract_referenced_commands(text: str) -> set[str]:
    commands = set(PR_AGENT_COMMAND_RE.findall(text))
    known_cli_words = {"fetch", "review", "review-action", "eval-dataset"}
    commands.update(command for command in BACKTICK_COMMAND_RE.findall(text) if command in known_cli_words)
    return commands


def _is_docs_path(path: str) -> bool:
    pure_path = PurePosixPath(path)
    return pure_path.suffix.lower() in DOC_EXTENSIONS or any(part.lower() == "docs" for part in pure_path.parts)


def _is_test_or_eval_path(path: str) -> bool:
    parts = {part.lower() for part in PurePosixPath(path).parts}
    name = PurePosixPath(path).name.lower()
    return bool(parts & {"test", "tests", "spec", "specs", "evaluation"}) or name.startswith("test_") or name.endswith("_test.py")


class RepositoryEvidence:
    def __init__(self, repo_root: Path, change_set: ChangeSet) -> None:
        self.repo_root = repo_root
        self.change_set = change_set
        self.changed_paths = {self._normalize(file.filename) for file in change_set.files}
        self._all_paths: set[str] | None = None
        self._test_paths: set[str] | None = None
        self._function_annotations: dict[str, dict[str, str]] = {}
        self._model_field_optional: dict[str, dict[str, bool]] | None = None
        self._defined_cli_commands: set[str] | None = None

    def related_test_paths(self, source_file: str) -> set[str]:
        normalized_source = self._normalize(source_file)
        candidates = self._related_test_candidates(normalized_source)
        exact_hits = {path for path in self.test_paths() if path in candidates}

        source_path = PurePosixPath(normalized_source)
        source_stem = source_path.stem.lower()
        parent_stem = source_path.parent.name.lower()
        heuristic_hits = {
            path
            for path in self.test_paths()
            if _path_stem_matches(path, source_stem, parent_stem)
        }
        return exact_hits | heuristic_hits

    def test_paths(self) -> set[str]:
        if self._test_paths is None:
            self._test_paths = {path for path in self.all_paths() | self.changed_paths if _is_test_or_eval_path(path)}
        return self._test_paths

    def all_paths(self) -> set[str]:
        if self._all_paths is not None:
            return self._all_paths

        paths = set(self.changed_paths)
        if self.repo_root.exists():
            for path in self.repo_root.rglob("*"):
                if not path.is_file() or _has_skipped_part(path):
                    continue
                try:
                    paths.add(self._normalize(path.relative_to(self.repo_root).as_posix()))
                except ValueError:
                    continue
        self._all_paths = paths
        return paths

    def field_is_known_non_optional(self, file_path: str, variable_name: str, field_name: str) -> bool:
        annotation = self._argument_annotations(file_path).get(variable_name)
        if annotation is None:
            return False
        model_fields = self._model_fields().get(annotation)
        if model_fields is None or field_name not in model_fields:
            return False
        return not model_fields[field_name]

    def defined_cli_commands(self) -> set[str]:
        if self._defined_cli_commands is not None:
            return self._defined_cli_commands

        cli_path = self.repo_root / "src" / "pr_agent" / "cli.py"
        commands: set[str] = set()
        if cli_path.exists():
            tree = _parse_python_file(cli_path)
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        command = node.name.replace("_", "-")
                        for decorator in node.decorator_list:
                            if _is_app_command_decorator(decorator):
                                command = _command_name_from_decorator(decorator) or command
                                commands.add(command)
        self._defined_cli_commands = commands
        return commands

    def _argument_annotations(self, file_path: str) -> dict[str, str]:
        normalized_path = self._normalize(file_path)
        if normalized_path in self._function_annotations:
            return self._function_annotations[normalized_path]

        annotations: dict[str, str] = {}
        full_path = self.repo_root / normalized_path
        tree = _parse_python_file(full_path)
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                        if arg.annotation is None:
                            continue
                        annotation_name = _annotation_name(arg.annotation)
                        if annotation_name:
                            annotations[arg.arg] = annotation_name
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    annotation_name = _annotation_name(node.annotation)
                    if annotation_name:
                        annotations[node.target.id] = annotation_name
        self._function_annotations[normalized_path] = annotations
        return annotations

    def _model_fields(self) -> dict[str, dict[str, bool]]:
        if self._model_field_optional is not None:
            return self._model_field_optional

        models: dict[str, dict[str, bool]] = {}
        python_paths = self.repo_root.rglob("*.py") if self.repo_root.exists() else []
        for path in python_paths:
            if _has_skipped_part(path):
                continue
            tree = _parse_python_file(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                fields: dict[str, bool] = {}
                for statement in node.body:
                    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                        fields[statement.target.id] = _annotation_allows_none(statement.annotation)
                if fields:
                    models[node.name] = fields
        self._model_field_optional = models
        return models

    def _related_test_candidates(self, source_file: str) -> set[str]:
        candidates = {self._normalize(path) for path in infer_related_test_files(source_file)}
        path = PurePosixPath(source_file)
        if path.suffix == ".py":
            without_src = PurePosixPath(str(path).removeprefix("src/"))
            parts = list(without_src.with_suffix("").parts)
            joined = "_".join(parts)
            stem = path.stem
            parent = path.parent.name
            candidates.update(
                {
                    f"tests/test_{stem}.py",
                    f"tests/test_{parent}_{stem}.py",
                    f"tests/test_{joined}.py",
                    f"tests/{without_src.parent.as_posix()}/test_{stem}.py",
                }
            )
        return {self._normalize(path) for path in candidates}

    @staticmethod
    def _normalize(path: str) -> str:
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized


def _path_stem_matches(path: str, source_stem: str, parent_stem: str) -> bool:
    test_path = PurePosixPath(path)
    test_stem = test_path.stem.lower()
    if source_stem not in test_stem:
        return False
    return parent_stem in test_stem or test_stem in {f"test_{source_stem}", f"{source_stem}_test"}


def _parse_python_file(path: Path) -> ast.AST | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _has_skipped_part(path: Path) -> bool:
    return any(part.lower() in SKIP_DIRS for part in path.parts)


def _is_app_command_decorator(decorator: ast.expr) -> bool:
    call = decorator if isinstance(decorator, ast.Call) else None
    if call is None:
        return False
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == "command"


def _command_name_from_decorator(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call) or not decorator.args:
        return None
    first_arg = decorator.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _annotation_name(annotation: ast.expr) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Subscript):
        return _annotation_name(annotation.value)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.split(".")[-1]
    if isinstance(annotation, ast.BinOp):
        return _annotation_name(annotation.left) or _annotation_name(annotation.right)
    return None


def _annotation_allows_none(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Constant):
        return annotation.value is None or annotation.value == "None"
    if isinstance(annotation, ast.Name):
        return annotation.id == "None"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _annotation_allows_none(annotation.left) or _annotation_allows_none(annotation.right)
    if isinstance(annotation, ast.Subscript):
        name = _annotation_name(annotation.value)
        if name == "Optional":
            return True
        if name == "Union":
            return _annotation_allows_none(annotation.slice)
    if isinstance(annotation, ast.Tuple):
        return any(_annotation_allows_none(element) for element in annotation.elts)
    return False
