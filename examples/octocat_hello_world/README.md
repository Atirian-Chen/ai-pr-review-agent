# Octocat Hello World Demo / Octocat 示例说明

This directory contains a saved demo run of AI PR Review Agent against the public PR:

本目录保存了一次针对公开 PR 的 AI PR Review Agent 示例运行结果：

```text
https://github.com/octocat/Hello-World/pull/1
```

## Why This Example / 示例来源

`octocat/Hello-World` is GitHub's classic demo repository. PR #1 edits the repository README and introduces several command-description lines where the shell command and its explanation are concatenated without spacing. It is a small, public, easy-to-inspect PR, which makes it useful for demonstrating the review pipeline without depending on a private repository.

`octocat/Hello-World` 是 GitHub 经典示例仓库。PR #1 修改了 README，并引入了几行“命令和解释文字粘在一起”的内容。这个 PR 很小、公开、容易人工核对，因此适合用来展示本项目的 review 流程，而不依赖私有仓库。

## Command / 运行命令

After installing the project and filling `.env`, the full review can be reproduced with:

安装项目并填写 `.env` 后，可以用下面的命令复现完整 review：

```powershell
.\.venv-win\Scripts\pr-agent.exe review https://github.com/octocat/Hello-World/pull/1 --out examples/octocat_hello_world
```

The CLI also supports a fetch-only mode for inspecting GitHub metadata and parsed diff hunks before calling the LLM:

CLI 也支持只抓取 PR 元数据和解析后 diff，不调用 LLM：

```powershell
.\.venv-win\Scripts\pr-agent.exe fetch https://github.com/octocat/Hello-World/pull/1 --out outputs/octocat_fetch
```

## Output Files / 输出说明

- `review_result.json`: Structured machine-readable output, including PR metadata, validated findings, model info, metrics, and trace ID.
- `review_report.md`: Human-readable Markdown report rendered from the structured result.
- `trace.jsonl`: Generated during local review runs for per-file trace rows. This committed demo keeps the JSON result and Markdown report as the stable portfolio artifacts.

- `review_result.json`：结构化结果，包含 PR 元数据、校验后的 findings、模型信息、指标和 trace ID。
- `review_report.md`：由结构化结果渲染出来的 Markdown 报告，适合直接阅读。
- `trace.jsonl`：本地运行 review 时会生成的逐文件 trace 日志。本次提交的示例保留 JSON 结果和 Markdown 报告作为稳定展示产物。

## What To Notice / 看点

The demo finding points to `README:2` and reports a maintainability/readability issue: the added command `$ mkdir ~/Hello-World` is joined directly with explanatory prose. This shows the intended behavior of the MVP:

这个示例 finding 指向 `README:2`，指出一个 maintainability/readability 问题：新增的 `$ mkdir ~/Hello-World` 命令和说明文字直接拼在了一起。它展示了 MVP 希望体现的几个能力：

- It fetches a real GitHub PR instead of using a handcrafted diff.
- It parses changed lines and keeps file/line references in the output.
- It asks the model for conservative findings grounded in the diff.
- It validates and renders the result into both JSON and Markdown.

- 从真实 GitHub PR 获取数据，而不是手写假 diff。
- 解析变更行，并在输出中保留文件和行号。
- 要求模型只输出能被 diff 支撑的保守审查结论。
- 将结果校验后同时输出为 JSON 和 Markdown。
