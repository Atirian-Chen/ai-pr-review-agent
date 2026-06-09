# AI PR Review Agent / 面向 GitHub PR 的 AI 代码审查 Agent

## Version1 Update / 从 MVP 到 version1 的变化

`version1` 是在 `version_mvp` 基础上的一次完整功能扩展。MVP 版本主要证明了“读取 GitHub PR -> 解析 patch -> 构建上下文 -> 调用 LLM -> 输出 JSON/Markdown 报告”这条最小链路；`version1` 则把它推进成一个可以覆盖更多审查入口、可以在 GitHub Actions 中自动运行、并带有评测集与示例输出的工程化版本。

Compared with `origin/codex/version_mvp`, `version1` adds 44 changed files and roughly 2.6k lines of implementation, tests, examples, and docs. The main change is that the agent is no longer PR-only: it now treats PR, commit, compare range, and local git diff as different sources of the same `ChangeSet`.

与 `version_mvp` 相比，`version1` 的重点变化如下：

| Area | MVP | version1 |
| --- | --- | --- |
| Review target / 审查目标 | 只支持 GitHub PR URL | 支持 GitHub PR、GitHub commit、GitHub compare range、本地 `git diff` |
| Pipeline abstraction / 管线抽象 | PR 专用流程 | 新增 `ReviewTargetInfo`、`ReviewTargetRef`、`ChangeSet`，统一多来源变更 |
| CLI commands / 命令行 | `fetch`、`review` 面向 PR | `fetch <target>`、`review <target>` 自动识别目标，新增 `review-action`、`eval-dataset` |
| Local mode / 本地模式 | 不支持 | 支持 `local` 审查未提交的工作区变更，包含完整 unified diff 拆分 |
| GitHub Actions / 自动化 | 不发布 GitHub 评论 | 新增 `.github/workflows/ai-review.yml`，支持 PR 自动摘要评论和 push commit 评论 |
| Summary comments / 摘要评论 | 只生成本地报告 | 新增可更新的 PR summary comment，使用 marker 避免重复刷屏 |
| Evaluation / 评测 | 无评测集 | 新增 50 条 JSONL case，覆盖 target parser、diff parser、filter、Action event、schema、issue detection 等 |
| Example outputs / 示例输出 | 单个 demo 输出 | 新增 PR、commit、compare、local diff 四类示例输出 |
| LLM robustness / 模型鲁棒性 | 直接解析 JSON | 支持 fenced JSON/前后解释文本解析、JSON repair、timeout 配置、token usage 合并 |
| Environment loading / 环境变量 | 默认当前目录 `.env` | 自动从项目根目录定位 `.env`，并支持 `OPENAI_TIMEOUT_SECONDS` |
| Test coverage / 测试覆盖 | MVP 单测 | 当前 `55 passed`，新增多目标、GitHub Actions、评论、评测集、本地 diff 等测试 |

Version1 的新增代码主要落在这些模块：

- `src/pr_agent/targets/`: 统一解析 PR、commit、compare、local target。
- `src/pr_agent/review/runner.py`: 把 CLI 与 GitHub Actions 复用的 review pipeline 独立出来。
- `src/pr_agent/diff/full_parser.py`: 将完整 `git diff` 拆成文件级 patch，支持本地模式。
- `src/pr_agent/github/actions.py`: 将 GitHub Actions event 转换成 review target。
- `src/pr_agent/github/comments.py`: 生成 PR/commit summary comment。
- `src/pr_agent/evaluation/dataset.py`: 加载、统计和评分评测 JSONL。
- `examples/` 与 `evaluation/`: 提供可展示的审查结果与评测数据。

## 1. What It Does / 项目功能

AI PR Review Agent is a local-first code review agent for GitHub Pull Requests, GitHub commits, GitHub compare ranges, and local git diffs. It focuses on repository-aware context, structured LLM output, conservative review, result validation, reproducible reports, and evaluation.

AI PR Review Agent 是一个本地优先的 AI 代码审查 Agent，支持 GitHub PR、GitHub commit、GitHub compare range 和本地 git diff。它不是简单把 diff 丢给大模型，而是围绕 diff 解析、上下文构建、结构化输出、保守审查策略、结果校验、报告生成和评测数据做成的工程化 Agent。

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
- Repair or validate JSON model output, then validate findings with Pydantic schemas, confidence thresholds, file-path checks, and line-number checks.
- Generate `review_result.json`, `review_report.md`, and `trace.jsonl`.
- Optionally publish a GitHub summary comment in GitHub Actions.

## 2. Why I Built It / 项目背景

Most toy AI code review demos stop at "send the diff to an LLM and ask for comments." That is not enough for real engineering use. Code review quality depends on whether the system understands changed lines, nearby code, file type, repository hints, and whether model output can be validated and traced.

很多 AI Code Review 玩具项目只是“把 diff 发给大模型，让它吐几条建议”。这在工程上远远不够。真实代码审查的难点不只是调用模型，而是：

- How to parse PR/commit/range/local diffs into reliable changed-line structures.
- How to provide enough repository context without flooding the prompt.
- How to make model output machine-checkable.
- How to reduce false positives with conservative prompts and validators.
- How to preserve trace, latency, token usage, and reproducible reports.
- How to run the same review pipeline locally, from a PR URL, and inside CI.
- How to evaluate parser, schema, target detection, and issue-detection behavior over labeled cases.

## 3. Features / 核心能力

- **One review command / 一个 review 指令**: `pr-agent review <target>` supports PR, commit, compare, and local diff targets.
- **Target auto-detection / 自动识别目标**: Parses GitHub PR URLs, commit URLs, compare URLs, and `local`.
- **Shared ChangeSet abstraction / 统一 ChangeSet 抽象**: Normalizes target metadata, changed files, and parsed hunks before review.
- **Unified diff parser / Diff 解析**: Converts patch text into hunks and lines with old/new line numbers.
- **Full local diff parser / 完整本地 diff 解析**: Splits full `git diff` output into file-level patches for local working tree review.
- **Repository context retrieval / 仓库上下文检索**: Adds surrounding code, README snippets, and related test file candidates from GitHub or local files.
- **Conservative reviewer / 保守审查 Agent**: Prompts the LLM to report only issues supported by diff or context.
- **Structured findings / 结构化建议**: Uses `ReviewFinding` and `ReviewResult` schemas for reliable downstream processing.
- **JSON recovery / JSON 输出恢复**: Handles plain JSON, fenced JSON, JSON embedded in text, and one-shot JSON repair.
- **Quality gates / 质量过滤**: Filters low-confidence findings, invalid file paths, weak evidence, hallucinated line numbers, deterministic false positives, LLM-verifier rejections, and low-value style nits.
- **Markdown report / Markdown 报告**: Renders readable review reports for demos and portfolio presentation.
- **GitHub Actions review / GitHub Actions 自动审查**: Resolves `pull_request` and `push` events, runs review, uploads artifacts, and publishes summary comments.
- **Evaluation dataset / 评测数据集**: Provides 50 labeled JSONL cases and an `eval-dataset` command for coverage and scoring.

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
    - split full local git diff into file patches
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
    - JSON repair fallback
    ↓
Validator
    - Pydantic schema validation
    - confidence threshold
    - file path and line number checks
    - evidence and suggestion checks
    ↓
Renderer / Publisher
    - review_result.json
    - review_report.md
    - trace.jsonl
    - optional GitHub summary comment
```

这个设计把“变更来源”和“审查流程”解耦。PR、commit、compare、local diff 都先变成统一的 `ChangeSet`，后面的 context retrieval、LLM review、validator、renderer 和 GitHub Actions 发布流程都可以复用同一套逻辑。

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
VERIFIER_OPENAI_API_KEY=your_verifier_openai_or_compatible_api_key
VERIFIER_OPENAI_BASE_URL=https://api.openai.com/v1
VERIFIER_OPENAI_MODEL=gpt-4.1-mini
VERIFIER_OPENAI_TIMEOUT_SECONDS=60
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

Run GitHub Actions mode locally:

本地模拟 GitHub Actions 模式：

```powershell
.\.venv-win\Scripts\pr-agent.exe review-action --event-path path/to/event.json --event-name pull_request --dry-run
```

Run evaluation dataset validation:

运行评测数据集校验：

```powershell
.\.venv-win\Scripts\pr-agent.exe eval-dataset --dataset evaluation/cases.jsonl --out outputs/eval_report.json
```

Run tests:

运行测试：

```powershell
.\.venv-win\Scripts\python.exe -m pytest
```

Current test status:

当前测试状态：

```text
55 passed
```

## Use AI Review in Another GitHub Repository / 在其他 GitHub 仓库使用

本项目可以作为一个独立的 AI Review 工具，被其他 GitHub 仓库通过 GitHub Actions 自动调用。其他仓库不需要复制 `src/` 代码，只需要复制一个 workflow yml。

### 1. Copy the workflow / 复制 workflow

在本仓库中找到示例文件：

```text
examples/external_repo_github_action/ai-review.yml
```

把它复制到目标仓库的这个位置：

```text
.github/workflows/ai-review.yml
```

复制完成后，目标仓库结构应类似：

```text
target-repo/
  .github/
    workflows/
      ai-review.yml
```

### 2. What the workflow does / 这个 yml 做什么

当前示例会在目标仓库发生以下事件时自动运行：

```yaml
on:
  push:
    branches:
      - "**"
  pull_request:
    types:
      - opened
      - synchronize
      - reopened
      - ready_for_review
```

含义：

- `push`: 任意分支 push 后触发，review 本次 push 的 `before...after` 变更范围，并把 summary comment 发到本次 push 的 head commit。
- `pull_request.opened`: 新建 PR 后触发，review 这个 PR。
- `pull_request.synchronize`: PR 分支新增 commit 后触发，重新 review 这个 PR。
- `pull_request.reopened`: PR 重新打开后触发。
- `pull_request.ready_for_review`: draft PR 变成 ready 后触发。

### 3. Tool installation / 工具安装来源

示例 yml 会从本工具仓库安装 AI Review Agent：

```yaml
run: python -m pip install "git+https://github.com/Atirian-Chen/ai-pr-review-agent.git@v1.0.0"
```

因此，示例 yml 的可用前提是：

- `Atirian-Chen/ai-pr-review-agent` 对目标仓库的 GitHub Actions runner 可访问。
- `v1.0.0` tag 已经推送到 GitHub。

如果你后续改用新的 release/tag，例如 `v1.1.0`，把安装行改成：

```yaml
run: python -m pip install "git+https://github.com/Atirian-Chen/ai-pr-review-agent.git@v1.1.0"
```

如果本工具仓库是 private，目标仓库还需要额外配置读取本工具仓库的 token；public 仓库不需要。

### 4. Required GitHub Secret / 目标仓库必须配置的 Secret

每个使用该工具的目标仓库都必须配置：

```text
OPENAI_API_KEY
VERIFIER_OPENAI_API_KEY
```

配置位置：

```text
Target repository -> Settings -> Secrets and variables -> Actions -> New repository secret
```

Secret 名称填：

```text
OPENAI_API_KEY
```

Secret 值填模型服务商提供的 API key。

如果启用 LLM verifier，再新增一个 secret：

```text
VERIFIER_OPENAI_API_KEY
```

这个 key 专门给第二遍验证模型使用。没有配置时，工具仍会运行确定性 verifier，但会在结果统计里把 LLM verifier 标记为 skipped。

`GITHUB_TOKEN` 不需要手动创建，GitHub Actions 会自动提供：

```yaml
GITHUB_TOKEN: ${{ github.token }}
```

### 5. Adjustable parameters / yml 中可调参数

示例 yml 中模型相关参数是明文写在 workflow 里的：

```yaml
OPENAI_BASE_URL: https://api.deepseek.com
OPENAI_MODEL: deepseek-v4-pro
OPENAI_TIMEOUT_SECONDS: "500"
VERIFIER_OPENAI_BASE_URL: https://api.deepseek.com
VERIFIER_OPENAI_MODEL: deepseek-chat
VERIFIER_OPENAI_TIMEOUT_SECONDS: "120"
```

含义：

- `OPENAI_BASE_URL`: OpenAI-compatible API 地址。
- `OPENAI_MODEL`: 主 reviewer 使用的模型名，建议使用更强的推理模型。
- `OPENAI_TIMEOUT_SECONDS`: 主 reviewer 单次 LLM 请求超时时间，单位是秒。
- `VERIFIER_OPENAI_BASE_URL`: LLM verifier 使用的 OpenAI-compatible API 地址。
- `VERIFIER_OPENAI_MODEL`: 第二遍验证模型，建议使用 mini、flash、chat 等更便宜更快的模型。
- `VERIFIER_OPENAI_TIMEOUT_SECONDS`: LLM verifier 单次请求超时时间，单位是秒。

如果使用官方 OpenAI API，可以改成：

```yaml
OPENAI_BASE_URL: https://api.openai.com/v1
OPENAI_MODEL: gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS: "120"
VERIFIER_OPENAI_BASE_URL: https://api.openai.com/v1
VERIFIER_OPENAI_MODEL: gpt-4.1-mini
VERIFIER_OPENAI_TIMEOUT_SECONDS: "60"
```

如果使用 DeepSeek 或其他兼容服务，保持服务商要求的 URL 和模型名即可。

### 6. Required permissions / workflow 权限

示例 yml 需要这些权限：

```yaml
permissions:
  contents: write
  issues: write
  pull-requests: write
```

含义：

- `contents: write`: 允许在 push 场景给 head commit 写 commit comment。
- `issues: write`: 允许在 PR conversation 中创建或更新 summary comment。
- `pull-requests: write`: 允许读取 PR 元数据，并在 PR 场景下发布或更新 summary comment。

### 7. Expected result / 运行结果

配置完成后：

- 目标仓库 push 后，会自动 review 本次 push 的变更，并评论到最后一次 commit。
- 目标仓库 PR 创建或更新后，会自动 review PR，并在 PR conversation 中创建或更新一条 AI Review Summary。
- 每次运行都会上传 `outputs/github-action` 作为 GitHub Actions artifact，里面包含 `review_result.json`、`review_report.md`、`trace.jsonl` 和 `summary_comment.md`。

Troubleshooting:

故障排查：

If dependency installation fails on Windows MSYS/Git Bash with a `pydantic-core` build error, create the virtual environment with a standard CPython 3.11+ interpreter, for example the Python Launcher (`py -3.11 -m venv .venv-win`) or the installer from python.org.

If `review` fails with `ReadTimeout`, `LLM API request timed out`, or a provider-specific timeout, the LLM provider did not finish sending the response before the timeout. Increase `OPENAI_TIMEOUT_SECONDS` / `VERIFIER_OPENAI_TIMEOUT_SECONDS` in `.env`, or the matching `timeout_seconds` value in `configs/default.yml`, then retry.

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

Example GitHub summary comment:

示例 GitHub 摘要评论：

```markdown
<!-- ai-pr-review-agent:summary-comment -->
## AI Review Summary

- Target: `pull_request` `#123`
- Risk: Low
- Files reviewed: 3 / 5
- Findings: 1
- Model: gpt-4.1-mini

### Findings
1. **Minor / maintainability** `README.md:2`: Concatenated command and description without spacing (0.95)
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
- **CI integration without coupling / CI 集成但不绑死 CI**: GitHub Actions mode reuses the same runner as local CLI, so CI is an entry point rather than a separate review implementation.
- **No code execution / 不执行目标代码**: The agent only reads metadata, diffs, and file content. It does not run untrusted code.
- **Structured output first / 优先结构化输出**: Findings must match Pydantic schemas, so they can be filtered, sorted, evaluated, and rendered.
- **Conservative review strategy / 保守审查策略**: The prompt asks the LLM to report only issues supported by diff or context.
- **Validation after generation / 生成后校验**: The validator filters weak findings by confidence, file path, line number, evidence, and suggestion quality.
- **Repair before failure / 先修复再失败**: LLM output may contain markdown fences or extra text, so version1 attempts robust JSON extraction and repair before failing the run.
- **Lightweight context before vector RAG / 先做轻量上下文**: Version1 uses diff, surrounding code, README excerpts, and related test candidates before introducing embeddings.
- **Evaluation as a first-class artifact / 评测作为一等产物**: The project includes labeled cases so future iterations can measure parser, schema, and issue-detection changes.

## 8. Roadmap / 后续计划

Completed in version1:

version1 已完成：

- **Multi-target review / 多目标审查**: GitHub PR, commit, compare, and local diff now share one review pipeline.
- **GitHub workflow / GitHub 工作流**: Added GitHub Action triggers for `pull_request` and `push`.
- **PR summary comment / PR 摘要评论**: Added bot-generated summary comments with update markers.
- **Evaluation dataset / 评测集**: Added 50 labeled cases plus dataset validation and scoring helpers.

Next steps:

后续计划：

- **Specialized reviewers / 多维度 reviewer**: Split the current GeneralReviewer into Bug, Security, Performance, Test, and Maintainability reviewers.
- **Aggregator / 聚合器**: Deduplicate findings, sort by severity and confidence, and enforce per-category limits.
- **Repository config / 仓库级配置**: Support repository-level `ai-review.yml` for filters, thresholds, model, and reviewer switches.
- **Richer local mode / 更完整的本地模式**: Add staged-only, unstaged-only, and explicit `main..feature` local range support.
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
CI integration, and eventually evaluation.

AI 代码审查不是简单写一个 prompt。
它是围绕 diff 解析、仓库上下文、结构化模型输出、保守审查策略、
结果校验、报告生成、CI 集成以及后续评测构建的一套工程化流程。
```
