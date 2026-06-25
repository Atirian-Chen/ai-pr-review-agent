# Version 2.1 Design Report

[中文版本](version2_1_design_cn.md)

## Positioning

Version 2.1 turns the project from an LLM-only PR reviewer into an evidence-verified review harness.

The old v2.0 flow was:

```text
Reviewer -> Validator -> Report
```

The v2.1 flow is:

```text
Reviewer
  -> Verification Planner
  -> Policy Gate
  -> Tool Executor
  -> Evidence Adjudicator
  -> Publisher Gate
  -> Report
```

The goal is not to become an autonomous coding agent. The goal is to reduce false positives and make every important finding explain whether it was verified, which tools were used, what evidence was collected, and how that evidence changed the final publication decision.

## System Architecture

```text
Review Target
    |
    v
ChangeSet Loader
    |
    v
Diff Parser + Context Retriever
    |
    v
Reviewer
    |  candidate findings
    v
Coordinator + Validator
    |
    v
Verification Planner
    |  VerificationPlan
    v
Policy Gate
    |  approved tools only
    v
Tool Executor
    |-----------------------------|
    |                             |
    v                             v
Static Tools                 Sandbox Tools
repository_search            pytest runner
read_file                    ruff runner
test_discovery               mypy runner
dependency_inspection        no-network Docker
    |                             |
    |------------- ToolResult -----|
                  |
                  v
Evidence Adjudicator
    |
    v
Publisher Gate
    |
    v
JSON / Markdown / Trace / GitHub Summary
```

### Reviewer

The reviewer remains responsible for reading the diff and repository context and producing candidate findings. In multi-agent mode, specialized Bug, Test, Security, and Performance reviewers run separate passes before deterministic coordination.

Reviewer output is intentionally limited:

- It may describe a suspected issue.
- It may suggest verification intent, such as search terms or a likely test file.
- It must not provide raw shell commands.
- It must not provide Docker arguments.
- It must not request network access.

The output is parsed into structured schema objects and still goes through the existing validators before verification starts.

### Verification Planner

The Verification Planner converts a candidate finding into a conservative `VerificationPlan`.

The plan includes:

- `finding_id`
- verification goal
- requested tool kinds
- search terms
- candidate test paths
- rationale
- risk level

The planner uses both model-provided verification intent and deterministic defaults. The finding category strongly influences tool choice:

| Finding category | Typical tools |
| --- | --- |
| Bug | repository search, read file, test discovery, pytest, ruff, mypy |
| Test | repository search, test discovery, pytest |
| Security | repository search, read file, dependency inspection, ruff |
| Performance | repository search, read file, test discovery |

The planner is not trusted as an executor. Its output is advisory and must pass the Policy Gate.

### Policy Gate

The Policy Gate is deterministic. It decides whether a requested tool is allowed for the current finding, mode, workspace, path, and risk level.

It enforces:

- verification mode: `off`, `static`, or `sandbox`
- category-to-tool allowlists
- path allowlists and deny-lists
- sensitive file blocking
- search term sanitization
- sandbox eligibility
- budget and timeout limits

The most important design rule is that the model never gets to run commands directly. The system chooses from predefined tool implementations and command templates.

### Tool Executor

The Tool Executor runs approved tools and records compact `ToolResult` objects. Full logs go into artifact files instead of being embedded in `review_result.json`.

There are two tool classes:

- **Static tools**: read-only repository inspection.
- **Sandbox tools**: allowlisted checks executed inside a restricted Docker container.

Static tools are available in `static` and `sandbox` mode. Sandbox tools are available only in `sandbox` mode, and only when the workspace is local/trusted.

### Evidence Adjudicator

The Evidence Adjudicator receives:

- the original finding
- the approved verification plan
- the collected tool results

It returns a finding-level verification record:

- status: `supported`, `contradicted`, `inconclusive`, `skipped`, or `error`
- evidence summary
- confidence before and after
- publication decision
- compact tool result summaries

It must be conservative. Lack of evidence is not proof that a finding is false, and passing unrelated tests do not contradict a bug report.

## Tool System Design

### `repository_search`

Purpose:

- Search the local workspace for symbols, functions, classes, configuration keys, error names, or API names related to a finding.

Inputs:

- repository root
- sanitized search terms
- file count, file size, and result count limits

Outputs:

- matched paths
- matched line numbers
- short summary
- artifact file containing detailed matches

Restrictions:

- skips `.git`, virtualenvs, `node_modules`, build outputs, binary files, and archives
- refuses sensitive files such as `.env`, private keys, credentials, and SSH material
- does not use network access

Typical use:

- Find call sites for a possibly unsafe function.
- Check whether a claimed missing helper or config already exists.
- Collect static evidence around a changed symbol.

### `test_discovery`

Purpose:

- Find candidate tests related to a changed file or finding.

Inputs:

- changed file path
- finding file path
- candidate test paths
- search terms such as function names

Rules:

```text
src/foo/bar.py
  -> tests/test_bar.py
  -> tests/foo/test_bar.py
  -> src/foo/test_bar.py
  -> files containing "bar" or relevant function names
```

Outputs:

- candidate test paths
- confidence/reason summary
- artifact file with discovery details

Typical use:

- Refute broad missing-test claims when related tests already exist.
- Select minimal pytest targets for sandbox mode.

### `pytest` Runner

Purpose:

- Run targeted Python tests that are directly related to a finding.

Allowed command templates:

```text
python -m pytest -q <approved_test_path>
python -m pytest -q <approved_test_path>::<approved_test_name>
```

Restrictions:

- no arbitrary `python -c`
- no `pip install`
- no shell wrapping
- approved paths only
- sandbox mode only

Interpretation:

- A failing targeted regression test can support a finding.
- A passing unrelated test does not contradict a finding.
- A collection failure or missing dependency usually yields `inconclusive` or `error`.

### `ruff` Runner

Purpose:

- Run allowlisted static lint checks on approved paths.

Allowed command template:

```text
ruff check <approved_paths>
```

Typical use:

- Catch syntax errors, import issues, or simple static problems when the repository has ruff available.
- Provide supporting evidence for some bug or security findings.

Restrictions:

- no auto-fix mode
- no arbitrary config path supplied by the model
- sandbox mode only

### `mypy` Runner

Purpose:

- Run type checking on approved paths when type-checking is useful and configured.

Allowed command template:

```text
mypy <approved_paths>
```

Typical use:

- Support findings involving optional values, return types, incompatible arguments, or API contract breaks.

Restrictions:

- sandbox mode only
- bounded timeout
- approved paths only
- missing type dependencies are treated as inconclusive unless they directly support the finding

## Safety Model

### Allowlist Commands Only

The executor never accepts raw commands from the model. It maps approved tool kinds to fixed command templates.

Allowed sandbox command families:

```text
python -m pytest -q ...
ruff check ...
mypy ...
```

Everything else is denied by design.

### No Arbitrary Shell

The system rejects:

- `bash -c`
- `sh -c`
- `cmd /c`
- `powershell -Command`
- `python -c`
- shell metacharacters
- pipes and redirections
- chained commands
- install scripts
- network download commands such as `curl` or `wget`

### No Network

Sandbox Docker runs with:

```text
--network none
```

This prevents tests or reviewed code from contacting package registries, metadata endpoints, external services, or attacker-controlled hosts.

### Docker Isolation

Before execution, the workspace is copied into a cleaned temporary directory. The real user workspace is not mounted writable.

The cleaned copy excludes:

- `.git`
- `.env`
- private keys
- credential files
- virtual environments
- `node_modules`
- build outputs
- cache directories
- binary/archive files

Docker settings include:

```text
--network none
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 128
--memory 1g
--cpus 1.0
--read-only
--tmpfs /tmp:rw,noexec,nosuid,size=256m
--env PYTHONDONTWRITEBYTECODE=1
--env HOME=/tmp
```

Secrets such as `OPENAI_API_KEY`, `VERIFIER_OPENAI_API_KEY`, and `GITHUB_TOKEN` are not forwarded into the container.

## Verification Logic

### `supported`

A finding is supported when tool evidence directly backs the claim.

Examples:

- A targeted pytest fails with the exact exception described by the finding.
- Static search finds call sites proving the unsafe path can be reached.
- A static checker reports the same changed line or symbol described by the finding.

Default decision:

```text
status = supported
confidence_after = min(confidence_before + 0.10, 0.99)
publication_decision = publish
```

### `contradicted`

A finding is contradicted when evidence directly refutes the claim.

Examples:

- The model claims there are no related tests, but `test_discovery` finds relevant tests for the changed behavior.
- The model claims a value can be `None`, but repository search shows all callers validate it immediately before the call.
- The model reports a missing dependency, but dependency inspection shows it is declared.

Default decision:

```text
status = contradicted
confidence_after = 0.0
publication_decision = suppress
```

### `inconclusive`

A finding is inconclusive when the tools cannot prove or refute it.

Examples:

- Related tests do not exist.
- Tests pass but do not cover the specific branch described by the finding.
- Static search finds the symbol but not enough call-path evidence.
- Sandbox cannot run because dependencies are missing.

Default decision:

```text
status = inconclusive
confidence_after = max(confidence_before - 0.10, 0.0)
publication_decision = publish_with_warning or suppress
```

High-severity/high-confidence findings can still be published with a warning. Medium and low signal findings are more likely to be suppressed to reduce comment noise.

## Failure Cases

### Flaky Test

A flaky test failure should not automatically support a finding.

Handling:

- Mark the tool result as failed or inconclusive.
- Record the failure summary and log path.
- Prefer `inconclusive` unless the failure stack clearly maps to the finding and changed line.
- Do not convert generic flaky failure into a confident bug report.

### Unrelated Pytest Failure

An unrelated pytest failure should not support or contradict the finding.

Handling:

- If the failing test does not exercise the changed code or described behavior, mark evidence as `inconclusive`.
- Keep the log artifact for traceability.
- Avoid suppressing the finding only because an unrelated test failed.

### Missing Dependency

Missing dependencies are common in sandboxed or minimal CI environments.

Handling:

- If dependency inspection shows pytest/ruff/mypy is unavailable, skip that execution tool.
- Static tools can still run.
- Mark the finding `inconclusive` rather than `contradicted`.
- Use `error` only when the tool invocation itself failed unexpectedly rather than being inapplicable.

## Outputs

Normal review outputs:

- `review_result.json`
- `review_report.md`
- `trace.jsonl`

v2.1 verification outputs:

- `verification_report.json`
- `artifacts/verification/<finding-id>/search_result.json`
- `artifacts/verification/<finding-id>/test_discovery.json`
- `artifacts/verification/<finding-id>/tool_result.json`
- sandbox logs such as `pytest.log`, `ruff.log`, and `mypy.log`

## Compatibility

`--verify off` is the default and preserves v2.0 behavior. Verification fields are optional, so existing review JSON remains readable.
