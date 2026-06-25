# AI PR Review Agent

[中文版本](README_cn.md)

AI PR Review Agent is a local-first code review harness for GitHub pull requests, commits, compare ranges, and local diffs. It parses code changes into a shared `ChangeSet`, retrieves lightweight repository context, runs specialized reviewers, validates structured findings, and writes reproducible JSON, Markdown, trace, and verification artifacts.

The project is intentionally not an autonomous coding agent. It is a controlled review system: the model proposes findings, while the harness owns target loading, context, validation, evidence collection, reporting, and safety boundaries.

## Version 2.1 - Evidence-Verified Agent

### Problem Statement

LLM-only PR review can be useful, but it has three recurring problems:

- **Hallucination**: the model may infer behavior that is not actually present in the repository.
- **False positives**: plausible-sounding issues can become noisy PR comments.
- **No verification trail**: a finding often cannot explain which tools checked it, what evidence was collected, or whether the evidence supported or contradicted it.

v2.1 addresses this by adding a controlled verification layer after candidate findings are generated.

### Core Idea

```text
Candidate Finding
    |
    v
Verification Plan
    |
    v
Policy Gate
    |
    v
Tool Execution
    |
    v
Evidence Adjudication
    |
    v
Final Decision
```

The reviewer can suggest verification intent, but it cannot execute arbitrary commands. A deterministic policy decides which tools are allowed, the executor collects bounded evidence, and the adjudicator decides whether that evidence supports, contradicts, or cannot confirm the finding.

### Verification Modes

| Mode | Behavior | Intended Use |
| --- | --- | --- |
| `off` | No verification tools run. This preserves v2.0 behavior. | Fast review, baseline comparison, or low-risk use. |
| `static` | Read-only tools run, such as repository search, file reads, test discovery, and dependency inspection. | Safe default for local and CI review, including fork PRs. |
| `sandbox` | Static tools plus allowlisted Docker checks such as targeted `pytest`, `ruff`, and `mypy`. | Local workspaces or trusted CI checkouts where code execution is acceptable. |

### Verification Outcomes

| Outcome | Meaning | Publication Effect |
| --- | --- | --- |
| `supported` | Tool evidence directly supports the finding, for example a targeted test fails on the changed path. | Publish and may raise confidence. |
| `contradicted` | Tool evidence directly refutes the finding, for example a claimed missing test already exists and covers the behavior. | Suppress the finding. |
| `inconclusive` | The tools did not provide enough evidence either way. Passing tests alone do not prove the bug is absent. | Publish with warning or suppress depending on severity and policy. |

### Simple End-to-End Example

Candidate finding:

```text
Potential None dereference in src/profile.py: user.display_name is read before checking user is None.
```

Verification flow:

```text
1. Verification Plan
   Goal: confirm whether the None-input path is unsafe.
   Tools: repository_search, test_discovery, pytest.

2. Policy Gate
   Allows repository_search and test_discovery in static mode.
   Allows targeted pytest only in sandbox mode and only for approved test paths.

3. Tool Execution
   repository_search finds display_name call sites.
   test_discovery finds tests/test_profile.py.
   pytest runs python -m pytest -q tests/test_profile.py::test_display_name_none.

4. Evidence Adjudication
   If pytest fails with AttributeError on the changed line:
     status = supported
     decision = publish
   If an existing test already proves the None path is guarded:
     status = contradicted
     decision = suppress
   If no relevant test exists:
     status = inconclusive
     decision = publish_with_warning or suppress by policy
```

### What Changed From v2.0

- Added finding-level verification plans, tool results, evidence summaries, confidence changes, and publication decisions.
- Added a deterministic policy gate so the LLM cannot run raw shell commands.
- Added static tools for repository search, file reads, test discovery, and dependency inspection.
- Added sandbox tool execution for tightly allowlisted checks in Docker with no network and no forwarded secrets.
- Added `verification_report.json` and `artifacts/verification/<finding-id>/...` outputs.
- Added evidence adjudication for `supported`, `contradicted`, and `inconclusive` decisions.
- Added publish gating so contradicted or weak inconclusive findings can be suppressed.
- Added live E2E cases and manual judgement reports for Python and C++ review behavior.

### Review Commands

```powershell
pr-agent review local `
  --out outputs/local-review `
  --verify static `
  --workspace . `
  --verification-budget 3 `
  --verification-timeout 45
```

Standalone verification:

```powershell
pr-agent verify outputs/local-review/review_result.json --workspace . --mode static --out outputs/verified-review
```

### v2.1 Output Files

- `review_result.json`: structured review result with finding-level verification data.
- `review_report.md`: human-readable report.
- `trace.jsonl`: review and verification trace.
- `verification_report.json`: verification metrics and per-finding records.
- `artifacts/verification/<finding-id>/search_result.json`: repository search evidence.
- `artifacts/verification/<finding-id>/test_discovery.json`: related test discovery evidence.
- `artifacts/verification/<finding-id>/pytest.log`: sandbox test logs when sandbox mode is used.

### Expanded Live E2E Manual Run

Command:

```powershell
python -m pr_agent.main run-live-e2e --cases evaluation/live_e2e_cases.jsonl --out outputs/live-e2e-expanded --verify static --verification-budget 3 --verification-timeout 45
```

Summary:

- Dataset: 20 cases, Python + C++.
- Main run: 19 completed, 1 provider disconnect (`LIVE017`).
- Retry: `LIVE017` completed separately.
- Verification mode: `static`; most verification results are expected to stay `inconclusive`.
- Detailed report: `outputs/live-e2e-expanded/manual_judgement_report.md`.

| Case | Type | Expected | Manual Result |
| --- | --- | --- | --- |
| LIVE001 | Python bug | None dereference before guard | Found; extra related test noise |
| LIVE002 | Python security | SQL injection via f-string | Found; duplicate security finding suppressed |
| LIVE003 | Python security | Authorization token logging | Found; extra test noise |
| LIVE004 | Python mixed | Unsafe YAML + N+1 lookup | Found both; avoided SQL false positive |
| LIVE005 | Python clean | Parameterized SQL should be clean | Clean result |
| LIVE006 | Python clean | Guarded refactor should avoid None false positive | Avoided target false positive, but noisy test/contract findings |
| LIVE007 | Python clean/tests | Existing tests should suppress broad test complaint | Clean result; evidence gate suppressed candidates |
| LIVE008 | Python performance | Cache disable is benchmark-dependent | Cautious performance warning; static evidence inconclusive |
| LIVE009 | Python blocker | SyntaxError/import blocker | Found |
| LIVE010 | Python conditional crash | Divide-by-zero when `total == 0` | Found; extra test noise |
| LIVE011 | Python logic/security | Authorization ownership check inverted | Found; duplicate bug/security/test noise |
| LIVE012 | Python concurrency | Lock removed, race/lost update | Found; static evidence inconclusive |
| LIVE013 | Python resource leak | File handle leak | Found; category noise across bug/security/test |
| LIVE014 | Python clean concurrency | Lock retained, should be clean | Clean result; low-value test candidate suppressed |
| LIVE015 | C++ blocker | Missing semicolon compile failure | Found |
| LIVE016 | C++ conditional crash | Null pointer dereference before guard | Found; extra test noise |
| LIVE017 | C++ lifetime | Dangling `c_str()` pointer | Partial; retry succeeded, root cause mentioned but public finding was only a test finding |
| LIVE018 | C++ memory | Early-return memory leak | Partial; root cause recognized, but public finding was only a test finding |
| LIVE019 | C++ concurrency | Mutex removed, data race | Found; static evidence inconclusive |
| LIVE020 | C++ clean RAII | RAII ownership should avoid memory false positive | Avoided memory/pointer false positive, but published test noise |

Manual takeaway: the agent catches obvious crash, build, security, logic, and lock-removal issues well in both Python and C++. The main weakness is publication quality: duplicate root causes, test-review noise, and C++ memory/lifetime bugs sometimes being surfaced only as missing-test findings.

## Version 2.0 Update

v2.0 changed the reviewer from a single broad pass into a coordinated multi-reviewer system:

- **Multi-agent reviewers**: Bug, Test, Security, and Performance reviewers run specialized passes.
- **Coordinator**: deterministic coordination deduplicates and ranks findings.
- **Patch suggestions**: findings can include structured fix plans and optional patch snippets.
- **Test suggestions**: findings can include test scenarios, assertions, and optional test code.
- **PR-level evaluation**: `eval-report` measures validity, false positives, line hits, fixability, latency, and token usage.

## Version 1 Update

Version 1 turned the MVP into a broader engineering harness:

- Added support for GitHub PR URLs, commit URLs, compare URLs, and local diffs.
- Introduced shared target and change models such as `ReviewTargetInfo`, `ReviewTargetRef`, and `ChangeSet`.
- Added GitHub Actions review with summary comments.
- Added local diff parsing and example outputs.
- Added evaluation datasets and schema checks.
- Improved JSON recovery, environment loading, tracing, and token accounting.

## Core Features

- **One review command**: `pr-agent review <target>` supports PR, commit, compare, and local targets.
- **Target auto-detection**: GitHub PR URLs, commit URLs, compare URLs, and `local`.
- **Shared ChangeSet abstraction**: normalizes target metadata, changed files, and parsed hunks.
- **Unified diff parsing**: tracks old and new line numbers for changed lines.
- **Repository context retrieval**: surrounding code, README excerpts, and related test candidates.
- **Multi-agent review**: Bug, Test, Security, and Performance passes.
- **Structured findings**: Pydantic schemas for reliable downstream processing.
- **Quality gates**: confidence thresholding, file path checks, line validation, deterministic false-positive filters, and optional LLM verification.
- **Markdown and JSON reports**: reproducible local artifacts.
- **GitHub Actions support**: automated review and summary comments.
- **Evaluation harness**: labeled datasets, runnable PR cases, verification cases, and live E2E cases.

## Architecture

```text
Review Target
    |
    v
Target Parser
    |
    v
ChangeSet Loader
    |
    v
Diff Parser + File Filter
    |
    v
Context Retriever
    |
    v
Multi-Agent Reviewer
    |
    v
Coordinator + Validator
    |
    v
Verification Planner
    |
    v
Policy Gate
    |
    v
Static Tools / Sandbox Tools
    |
    v
Evidence Adjudicator
    |
    v
JSON / Markdown / Trace / GitHub Summary
```

## Quick Start

Create and install a virtual environment:

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
```

Fill `.env`:

```env
GITHUB_TOKEN=your_github_token
OPENAI_API_KEY=your_openai_or_compatible_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=120
VERIFIER_OPENAI_API_KEY=your_verifier_openai_or_compatible_api_key
VERIFIER_OPENAI_BASE_URL=https://api.openai.com/v1
VERIFIER_OPENAI_MODEL=gpt-4.1-mini
VERIFIER_OPENAI_TIMEOUT_SECONDS=60
```

Run a review:

```powershell
# GitHub PR
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/pull/123 --out outputs/pr-review

# GitHub commit
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/commit/<sha> --out outputs/commit-review

# GitHub compare range
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/compare/main...feature --out outputs/compare-review

# Local diff
.\.venv-win\Scripts\pr-agent.exe review local --out outputs/local-review --verify static --workspace .
```

Fetch metadata and parsed diff only:

```powershell
.\.venv-win\Scripts\pr-agent.exe fetch local --out outputs/local-fetch
```

## CLI Commands

| Command | Purpose |
| --- | --- |
| `fetch <target>` | Load target metadata and parse changed files without running review. |
| `review <target>` | Run the full review pipeline and write JSON, Markdown, and trace files. |
| `verify <review_result.json>` | Verify findings from an existing review result. |
| `review-action` | Resolve GitHub Actions event context and publish a summary comment. |
| `eval-dataset` | Validate the labeled evaluation dataset. |
| `eval-report` | Build PR-level evaluation metrics from cases and predictions. |
| `eval-verification` | Summarize verification evaluation cases. |
| `eval-run` | Run executable PR evaluation cases with deterministic or live LLM mode. |
| `run-live-e2e` | Run live LLM E2E cases and write outputs for manual judgement. |

## Testing and Evaluation

Run unit tests:

```powershell
pytest
```

Run verification case summary:

```powershell
python -m pr_agent.main eval-verification --cases evaluation/verification_cases.jsonl --out outputs/verification-eval.json
```

Run live E2E cases:

```powershell
python -m pr_agent.main run-live-e2e --cases evaluation/live_e2e_cases.jsonl --out outputs/live-e2e --verify static
```

Evaluation artifacts include:

- `evaluation/cases.jsonl`: parser, schema, filter, and issue-detection cases.
- `evaluation/pr_cases.jsonl`: PR-level evaluation cases.
- `evaluation/verification_cases.jsonl`: v2.1 verification status cases.
- `evaluation/live_e2e_cases.jsonl`: live LLM E2E cases for manual judgement.
- `examples/evaluation/run/`: deterministic runnable evaluation outputs.

## Safety Boundary

- The LLM never receives permission to run arbitrary shell commands.
- Static verification is read-only.
- Sandbox mode runs only allowlisted command templates.
- Docker sandbox execution uses no network, no forwarded secrets, dropped capabilities, resource limits, and a cleaned temporary workspace copy.
- Fork PRs in GitHub Actions are downgraded to static verification by default.
- The agent does not modify source code, commit changes, push branches, or auto-apply patches.

## Example Outputs

Generated review outputs include:

- `review_result.json`
- `review_report.md`
- `trace.jsonl`
- `verification_report.json`
- `artifacts/verification/...`

Example directories:

- `examples/octocat_hello_world/`
- `examples/octocat_commit/`
- `examples/octocat_compare/`
- `examples/evaluation/run/`
- `outputs/live-e2e-expanded/`

## Documentation

- [Version 2.0 design](docs/version2-design.md)
- [Version 2.1 design](docs/version2_1_design.md)
- [Sandbox security](docs/sandbox-security.md)
- [Verification evaluation](docs/verification-evaluation.md)
- [Agent harness design](docs/agent-harness-design.md)
