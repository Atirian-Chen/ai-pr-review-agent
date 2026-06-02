# AI PR Review Agent / 面向 GitHub PR 的 AI 代码审查 Agent

AI PR Review Agent is a local-first MVP for reviewing GitHub Pull Requests with repository-aware context, structured LLM output, and conservative validation.

AI PR Review Agent 是一个面向 GitHub Pull Request 的本地可运行 MVP。它不是简单把 PR diff 丢给大模型，而是围绕 PR diff 解析、仓库上下文构建、结构化输出、保守审查策略和结果校验做成的工程化 Agent。

## 1. What It Does / 项目功能

Given a GitHub PR URL, the agent can:

输入一个 GitHub PR URL 后，系统会自动完成：

- Fetch PR metadata and changed files from the GitHub REST API.
- Parse GitHub patch text into structured `DiffHunk` and `DiffLine` objects with old/new line numbers.
- Filter generated files, lock files, binary files, large patches, and removed files.
- Retrieve lightweight repository context, including surrounding code, README excerpts, and related test file candidates.
- Call an OpenAI-compatible LLM to generate conservative code review findings.
- Validate findings with Pydantic schemas and line-number checks.
- Generate `review_result.json`, `review_report.md`, and `trace.jsonl`.

对应中文能力：

- 通过 GitHub REST API 获取 PR 元数据和变更文件。
- 将 GitHub patch 解析为带新旧行号的结构化 diff。
- 跳过 lock 文件、构建产物、二进制文件、大 patch 和删除文件。
- 构建轻量仓库上下文，包括同文件变更行上下文、README 摘要和测试文件候选路径。
- 调用 OpenAI 兼容模型生成保守的代码审查建议。
- 使用 Pydantic schema、置信度阈值和行号校验过滤低质量结果。
- 输出 JSON 结构化结果、Markdown 报告和 trace 日志。

## 2. Why I Built It / 项目背景

Most toy AI code review demos stop at "send the diff to an LLM and ask for comments." That is not enough for real engineering use. Code review quality depends on whether the system understands changed lines, nearby code, file type, repository hints, and whether model output can be validated and traced.

很多 AI Code Review 玩具项目只是“把 diff 发给大模型，让它吐几条建议”。这在工程上远远不够。真实代码审查的难点不只是调用模型，而是：

- How to parse PR diffs into reliable changed-line structures.
- How to provide enough repository context without flooding the prompt.
- How to make the model output machine-checkable findings.
- How to reduce false positives with conservative prompts and validators.
- How to preserve trace, latency, token usage, and reproducible reports.

对应中文总结：

- 要能精确解析 PR diff 和变更行。
- 要能构建恰当的仓库上下文，而不是盲目塞整个仓库。
- 要强制模型输出可校验、可排序、可追踪的结构化结果。
- 要通过保守 prompt 和 validator 降低误报。
- 要保留 trace、延迟、token 和报告，形成工程闭环。

## 3. Features / 核心能力

- **GitHub PR ingestion / PR 获取**: Parses PR URLs and fetches PR metadata plus changed files.
- **Unified diff parser / Diff 解析**: Converts patch text into hunks and lines with old/new line numbers.
- **Repository context retrieval / 仓库上下文检索**: Adds surrounding code, README snippets, and related test file candidates.
- **Conservative reviewer / 保守审查 Agent**: Prompts the LLM to report only issues supported by diff or context.
- **Structured findings / 结构化建议**: Uses `ReviewFinding` and `ReviewResult` schemas for reliable downstream processing.
- **Quality gates / 质量过滤**: Filters low-confidence findings, invalid file paths, weak evidence, and hallucinated line numbers.
- **Markdown report / Markdown 报告**: Renders readable review reports for local demo and portfolio presentation.
- **Trace and metrics / Trace 与指标**: Records latency, model name, token usage, reviewed files, and trace ID.

## 4. Architecture / 系统架构

```text
GitHub PR URL
    ↓
GitHub Client
    - parse owner/repo/pull_number
    - fetch PR metadata
    - fetch changed files and patch text
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

中文说明：

这个 MVP 的核心设计是把一次 AI Review 拆成多个可测试、可替换的模块。GitHub Client 只负责读取 PR，Diff Parser 只负责结构化 patch，Context Retriever 只负责构建模型上下文，Reviewer 只负责模型调用，Validator 负责质量控制，Renderer 负责输出报告。这样后续要升级到多 reviewer、GitHub Action 或评测系统时，不需要推倒重来。

## 5. Quick Start / 快速开始

Create and install a virtual environment:

创建并安装虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
```

On this workspace, the default MSYS Python may fail to install `pydantic-core`. The tested environment uses the Codex bundled Windows Python:

在当前工作区，默认 MSYS Python 可能无法正常安装 `pydantic-core`。已经验证可用的方式是使用 Codex bundled Windows Python：

```powershell
C:\Users\Atirian\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-win\Scripts\python.exe -m pytest
```

Fill `.env`:

填写 `.env`：

```env
GITHUB_TOKEN=your_github_token
OPENAI_API_KEY=your_openai_or_compatible_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

Fetch PR metadata and structured diff only:

只获取 PR 元数据和结构化 diff：

```powershell
.\.venv-win\Scripts\pr-agent.exe fetch https://github.com/owner/repo/pull/123 --out outputs/demo
```

Run the full MVP review:

运行完整 MVP review：

```powershell
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/pull/123 --out outputs/demo
```

Run tests:

运行测试：

```powershell
.\.venv-win\Scripts\python.exe -m pytest
```

Current test status:

当前测试状态：

```text
23 passed
```

## 6. Example Output / 示例输出

Example PR:

示例 PR：

```text
https://github.com/octocat/Hello-World/pull/1
```

Generated example files:

生成的示例文件：

- `examples/octocat_hello_world/review_result.json`
- `examples/octocat_hello_world/review_report.md`

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

- **Local MVP first / 先做本地 MVP**: The first version focuses on a reliable CLI, JSON output, and Markdown report before GitHub comments or UI.
- **No code execution / 不执行 PR 代码**: The agent only reads PR metadata and repository content. It does not run untrusted code from the PR.
- **Structured output first / 优先结构化输出**: Findings must match Pydantic schemas, so they can be filtered, sorted, evaluated, and rendered.
- **Conservative review strategy / 保守审查策略**: The prompt asks the LLM to report only issues supported by diff or context.
- **Validation after generation / 生成后校验**: The validator filters weak findings by confidence, file path, line number, evidence, and suggestion quality.
- **Lightweight context before vector RAG / 先做轻量上下文**: MVP uses diff, surrounding code, README excerpts, and related test file candidates before introducing embeddings.
- **OpenAI-compatible API / OpenAI 兼容接口**: The LLM client works with OpenAI and compatible model providers through `OPENAI_BASE_URL` and `OPENAI_MODEL`.

## 8. Roadmap / 后续计划

- **V1 GitHub workflow / GitHub 工作流**: Add GitHub Action triggers for `pull_request` events.
- **PR summary comment / PR 摘要评论**: Publish or update a bot-generated summary comment on the PR.
- **Specialized reviewers / 多维度 reviewer**: Split the current GeneralReviewer into Bug, Security, Performance, Test, and Maintainability reviewers.
- **Aggregator / 聚合器**: Deduplicate findings, sort by severity and confidence, and enforce per-category limits.
- **Configuration file / 配置文件**: Support repository-level `ai-review.yml` for filters, thresholds, model, and reviewer switches.
- **Evaluation dataset / 评测集**: Build 20+ PR cases with manual labels for valid, partial, invalid, and unknown findings.
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
It is an engineering pipeline around PR diff parsing, repository context,
structured model output, conservative review policy, validation, reporting,
and eventually evaluation.

AI 代码审查不是简单写一个 prompt。
它是围绕 PR diff 解析、仓库上下文、结构化模型输出、保守审查策略、
结果校验、报告生成以及后续评测构建的一套工程化流程。
```
