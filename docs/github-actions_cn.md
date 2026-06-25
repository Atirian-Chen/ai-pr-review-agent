# GitHub Actions 自动审查

[English version](github-actions.md)

`.github/workflows/ai-review.yml` 中的 workflow 会自动运行 AI review。

## 触发条件

- `push`：把 push 的 commit range 当作 GitHub compare target 审查，并在 head commit 上发布 summary comment。
- `pull_request`：审查 PR，并在 PR conversation 中创建或更新一条 summary comment。

## 必需 Secrets

```text
OPENAI_API_KEY
VERIFIER_OPENAI_API_KEY
```

`OPENAI_API_KEY` 用于主 reviewer 模型。`VERIFIER_OPENAI_API_KEY` 用于可选的第二轮 verifier 模型。如果没有配置 `VERIFIER_OPENAI_API_KEY`，确定性 verifier 仍会运行，LLM verifier 会标记为 skipped。

Workflow 会把 GitHub 内置 token 作为 `GITHUB_TOKEN` 传入。

## 模型环境变量

主 reviewer：

```yaml
OPENAI_BASE_URL: https://api.deepseek.com
OPENAI_MODEL: deepseek-v4-pro
OPENAI_TIMEOUT_SECONDS: "500"
```

LLM verifier：

```yaml
VERIFIER_OPENAI_BASE_URL: https://api.deepseek.com
VERIFIER_OPENAI_MODEL: deepseek-v4-flash
VERIFIER_OPENAI_TIMEOUT_SECONDS: "120"
```

主模型可以使用更强的推理模型。Verifier 模型通常可以用更便宜、更快的 mini、flash 或 chat 模型。

## v2.1 验证环境变量

```yaml
PR_AGENT_VERIFY_MODE: sandbox
PR_AGENT_VERIFY_MAX_FINDINGS: "3"
PR_AGENT_VERIFY_TIMEOUT_SECONDS: "45"
PR_AGENT_PUBLISH_POLICY: verified_or_high_confidence
```

`PR_AGENT_VERIFY_MODE` 可以是 `off`、`static` 或 `sandbox`。

- `off`：保持 v2 行为。
- `static`：运行只读仓库搜索、文件读取、测试发现和依赖检查。
- `sandbox`：额外允许无网络、无 secrets 的白名单 Docker 检查。

Fork PR 会由 `review-action` 自动从 `sandbox` 降级为 `static`。

## 权限

- `contents: write`：push event 上发布 commit comment 需要。
- `issues: write`：PR conversation comment 需要。
- `pull-requests: write`：读取 PR metadata 和发布 PR summary comment 需要。

## 本地 Dry Run

```powershell
pr-agent review-action --event-path path/to/event.json --event-name pull_request --dry-run
```

Dry run 会写出：

- `review_result.json`
- `review_report.md`
- `trace.jsonl`
- `github_action_target.json`
- `summary_comment.md`
- 启用 v2.1 verification 时的 `verification_report.json`
- v2.1 工具生成的 `artifacts/verification/`
