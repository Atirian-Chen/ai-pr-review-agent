# AI PR Review Agent / 面向 GitHub PR 的 AI 代码审查 Agent

AI PR Review Agent is a local-first code review agent for GitHub Pull Requests, GitHub commits, GitHub compare ranges, and local git diffs. It focuses on repository-aware context, structured LLM output, conservative review, and result validation.

AI PR Review Agent 是一个本地优先的 AI 代码审查 Agent，支持 GitHub PR、GitHub commit、GitHub compare range 和本地 git diff。它不是简单把 diff 丢给大模型，而是围绕 diff 解析、上下文构建、结构化输出、保守审查策略和结果校验做成的工程化 Agent。

## 1. What It Does / 项目功能

Given one review target, the same command can automatically detect the target type:

输入一个 review target 后，同一个命令会自动识别目标类型：

- `https://github.com/owner/repo/pull/123` for GitHub PR review.
- `https://github.com/owner/repo/commit/<sha>` for single-commit review.
- `https://github.com/owner/repo/compare/<base>...<head>` for compare/range review.
- `local` for uncommitted local git diff review against `HEAD`.

Core workflow:

核心流程：

- Fetch PR, commit, or compare metadata from the GitHub REST API, or read local `git diff`.
- Parse patch text into structured `DiffHunk` and `DiffLine` objects with old/new line numbers.
- Normalize every source into one shared `ChangeSet` model.
- Filter generated files, lock files, binary files, large patches, and removed files.
- Retrieve lightweight repository context, including surrounding code, README excerpts, and related test file candidates.
- Call an OpenAI-compatible LLM to generate conservative code review findings.
- Validate findings with Pydantic schemas, confidence thresholds, file-path checks, and line-number checks.
- Generate `review_result.json`, `review_report.md`, and `trace.jsonl`.

## 2. Why I Built It / 项目背景

Most toy AI code review demos stop at "send the diff to an LLM and ask for comments." That is not enough for real engineering use. Code review quality depends on whether the system understands changed lines, nearby code, file type, repository hints, and whether model output can be validated and traced.

很多 AI Code Review 玩具项目只是“把 diff 发给大模型，让它吐几条建议”。这在工程上远远不够。真实代码审查的难点不只是调用模型，而是：

- How to parse PR/commit/range/local diffs into reliable changed-line structures.
- How to provide enough repository context without flooding the prompt.
- How to make model output machine-checkable.
- How to reduce false positives with conservative prompts and validators.
- How to preserve trace, latency, token usage, and reproducible reports.

## 3. Features / 核心能力

- **One review command / 一个 review 指令**: `pr-agent review <target>` supports PR, commit, compare, and local diff targets.
- **Target auto-detection / 自动识别目标**: Parses GitHub PR URLs, commit URLs, compare URLs, and `local`.
- **Shared ChangeSet abstraction / 统一 ChangeSet 抽象**: Normalizes target metadata, changed files, and parsed hunks before review.
- **Unified diff parser / Diff 解析**: Converts patch text into hunks and lines with old/new line numbers.
- **Local git diff parser / 本地 diff 解析**: Splits full `git diff` output into file-level patches.
- **Repository context retrieval / 仓库上下文检索**: Adds surrounding code, README snippets, and related test file candidates.
- **Conservative reviewer / 保守审查 Agent**: Prompts the LLM to report only issues supported by diff or context.
- **Structured findings / 结构化建议**: Uses `ReviewFinding` and `ReviewResult` schemas for reliable downstream processing.
- **Quality gates / 质量过滤**: Filters low-confidence findings, invalid file paths, weak evidence, and hallucinated line numbers.
- **Markdown report / Markdown 报告**: Renders readable review reports for demos and portfolio presentation.

## 4. Architecture / 系统架构

```text
Review Target
    - GitHub PR URL
    - GitHub commit URL
    - GitHub compare URL
    - local git diff
    ↓
Target Parser
    - detect pull_request / commit / compare / local_diff
    ↓
ChangeSet Loader
    - fetch GitHub metadata and changed files
    - or read local git diff
    - normalize target + files + hunks_by_file
    ↓
Diff Parser
    - parse unified diff hunk headers
    - track old/new line numbers
    - produce DiffHunk and DiffLine
    ↓
File Filter
    - skip lock/generated/binary/large/removed files
    ↓
Context Retriever
    - target patch
    - surrounding code around changed lines
    - README excerpt
    - related test file candidates
    ↓
General Reviewer
    - OpenAI-compatible LLM call
    - conservative review prompt
    - JSON-only output requirement
    ↓
Validator
    - Pydantic schema validation
    - confidence threshold
    - file path and line number checks
    - evidence and suggestion checks
    ↓
Renderer
    - review_result.json
    - review_report.md
    - trace.jsonl
```

这个设计把“变更来源”和“审查流程”解耦。PR、commit、compare、local diff 都先变成统一的 `ChangeSet`，后面的 context retrieval、LLM review、validator、renderer 都复用同一套逻辑。

## 5. Quick Start / 快速开始

Create and install a virtual environment:

创建并安装虚拟环境：

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
```

This README uses `.venv-win` for Windows PowerShell commands to avoid confusion with MSYS/Mingw-created virtual environments, which expose executables under `bin/` instead of the standard Windows `Scripts/` directory. If you create a normal Windows CPython environment named `.venv`, replace `.venv-win` with `.venv` in the commands.

本 README 在 Windows PowerShell 命令中使用 `.venv-win`，是为了避免和 MSYS/Mingw Python 创建的 `.venv` 混淆；后者通常使用 `bin/`，而不是标准 Windows 的 `Scripts/`。如果你用标准 Windows CPython 创建名为 `.venv` 的环境，只需要把命令里的 `.venv-win` 换成 `.venv`。

Fill `.env`:

填写 `.env`：

```env
GITHUB_TOKEN=your_github_token
OPENAI_API_KEY=your_openai_or_compatible_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=120
```

Fetch metadata and structured diff only:

只获取元数据和结构化 diff：

```powershell
# GitHub PR
.\.venv-win\Scripts\pr-agent.exe fetch https://github.com/owner/repo/pull/123 --out outputs/pr-fetch

# GitHub commit
.\.venv-win\Scripts\pr-agent.exe fetch https://github.com/owner/repo/commit/<sha> --out outputs/commit-fetch

# GitHub compare/range
.\.venv-win\Scripts\pr-agent.exe fetch https://github.com/owner/repo/compare/main...feature --out outputs/compare-fetch

# Local uncommitted git diff against HEAD
.\.venv-win\Scripts\pr-agent.exe fetch local --out outputs/local-fetch
```

Run full review with the same command shape:

使用同一个 `review <target>` 指令运行完整审查：

```powershell
# GitHub PR
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/pull/123 --out outputs/pr-review

# GitHub commit
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/commit/<sha> --out outputs/commit-review

# GitHub compare/range
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/compare/main...feature --out outputs/compare-review

# Local uncommitted git diff against HEAD
.\.venv-win\Scripts\pr-agent.exe review local --out outputs/local-review
```

Run tests:

运行测试：

```powershell
.\.venv-win\Scripts\python.exe -m pytest
```

Current test status:

当前测试状态：

```text
36 passed
```

Troubleshooting:

故障排查：

If dependency installation fails on Windows MSYS/Git Bash with a `pydantic-core` build error, create the virtual environment with a standard CPython 3.11+ interpreter, for example the Python Launcher (`py -3.11 -m venv .venv-win`) or the installer from python.org.

If `review` fails with `ReadTimeout: The read operation timed out`, the LLM provider did not finish sending the response before the timeout. Increase `OPENAI_TIMEOUT_SECONDS` in `.env` or `llm.timeout_seconds` in `configs/default.yml`, then retry.

如果在 Windows MSYS/Git Bash 环境中安装依赖时遇到 `pydantic-core` 构建错误，建议改用标准 CPython 3.11+ 创建虚拟环境，例如 Python Launcher（`py -3.11 -m venv .venv-win`）或 python.org 安装版。

## 6. Example Output / 示例输出

Example targets:

示例目标：

```text
PR:      https://github.com/octocat/Hello-World/pull/1
Commit:  https://github.com/octocat/Hello-World/commit/7044a8a032e85b6ab611033b2ac8af7ce85805b2
Compare: https://github.com/octocat/Hello-World/compare/553c2077f0edc3d5dc5d17262f6aa498e69d6f8e...7044a8a032e85b6ab611033b2ac8af7ce85805b2
Local:   local
```

Generated example files:

生成的示例文件：

- PR example: `examples/octocat_hello_world/review_result.json`, `examples/octocat_hello_world/review_report.md`
- Commit example: `examples/octocat_commit/review_result.json`, `examples/octocat_commit/review_report.md`
- Compare example: `examples/octocat_compare/review_result.json`, `examples/octocat_compare/review_report.md`
- Local diff example: `examples/local_git_diff/review_result.json`, `examples/local_git_diff/review_report.md`

Example finding:

示例 finding：

```markdown
### 1. [Minor][maintainability] Concatenated command and description without spacing
- File: `README:2`
- Confidence: 0.95
- Evidence: +$ mkdir ~/Hello-WorldCreates a directory for your project called "Hello-World" in your user directory
- Why it matters: The added lines incorrectly combine the shell command and its explanation into a single string, making the README confusing and unreadable.
- Suggestion: Separate the command and its description, e.g., using a code block for the command and plain text for the explanation.
```

Example metrics:

示例指标：

```text
Findings: 1
Critical: 0
Major: 0
Minor: 1
Nit: 0
Model: deepseek-v4-pro
Latency seconds: 23.73
Estimated tokens: 1563
```

## 7. Design Decisions / 设计取舍

- **One command, multiple sources / 一个命令，多种来源**: Users keep using `review <target>` while the target parser handles PR, commit, compare, and local diff.
- **ChangeSet abstraction / ChangeSet 抽象**: Different source types are normalized before review, avoiding duplicated reviewer logic.
- **PR remains the main story / PR 仍是主线**: PR is still the best fit for GitHub code review workflows, while commit/compare/local support pre-PR and incremental scanning.
- **No code execution / 不执行目标代码**: The agent only reads metadata, diffs, and file content. It does not run untrusted code.
- **Structured output first / 优先结构化输出**: Findings must match Pydantic schemas, so they can be filtered, sorted, evaluated, and rendered.
- **Conservative review strategy / 保守审查策略**: The prompt asks the LLM to report only issues supported by diff or context.
- **Validation after generation / 生成后校验**: The validator filters weak findings by confidence, file path, line number, evidence, and suggestion quality.
- **Lightweight context before vector RAG / 先做轻量上下文**: MVP uses diff, surrounding code, README excerpts, and related test candidates before introducing embeddings.

## 8. Roadmap / 后续计划

- **GitHub workflow / GitHub 工作流**: Add GitHub Action triggers for `pull_request` events.
- **PR summary comment / PR 摘要评论**: Publish or update a bot-generated summary comment on the PR.
- **Specialized reviewers / 多维度 reviewer**: Split the current GeneralReviewer into Bug, Security, Performance, Test, and Maintainability reviewers.
- **Aggregator / 聚合器**: Deduplicate findings, sort by severity and confidence, and enforce per-category limits.
- **Repository config / 仓库级配置**: Support repository-level `ai-review.yml` for filters, thresholds, model, and reviewer switches.
- **Richer local mode / 更完整的本地模式**: Add staged-only, unstaged-only, and explicit `main..feature` local range support.
- **Evaluation dataset / 评测集**: Build 20+ PR/commit/compare/local cases with manual labels.
- **Metrics / 指标统计**: Track JSON valid rate, false positive rate, valid suggestion rate, line accuracy, latency, and cost.
- **Repository-level RAG / 仓库级 RAG**: Add keyword retrieval, AST/symbol extraction, and optional vector retrieval.
- **Review history / 审查历史**: Save repeated runs and compare finding changes over time.

## 9. Relation to My Internship Experience / 与淘天 AICR 实习的关系

This project is an open-source-style abstraction of my AICR-related internship experience. During the internship, I worked with AI-assisted code analysis, incremental code scanning, and AI-generated code comments. This project turns that industrial experience into a runnable and demonstrable LLM engineering system.

这个项目是我对淘天 AICR 相关实习经历的开源化抽象。在实习中，我接触过 AI 代码分析、存量/增量代码扫描和 AI 注释生成。这个项目把这些经历进一步沉淀成一个可运行、可测试、可展示的 LLM 应用工程项目。

The main story is:

核心叙事是：

```text
AI code review is not just an LLM prompt.
It is an engineering pipeline around diff parsing, repository context,
structured model output, conservative review policy, validation, reporting,
and eventually evaluation.

AI 代码审查不是简单写一个 prompt。
它是围绕 diff 解析、仓库上下文、结构化模型输出、保守审查策略、
结果校验、报告生成以及后续评测构建的一套工程化流程。
```
