# Sandbox 安全设计

[English version](sandbox-security.md)

## 威胁模型

Sandbox verification 可能会执行被审查仓库中的代码。这些代码是不可信的，尤其是来自 pull request 的代码。因此 sandbox 设计必须防止模型和被审查代码获得过大的 shell、网络、文件系统或 secret 访问权限。

## 模型边界

LLM 永远不能提供原始 shell 命令。它只能提出验证意图。系统会把批准后的工具转换成固定模板：

```text
python -m pytest -q <approved_test_path>
python -m pytest -q <approved_test_path>::<approved_test_name>
ruff check <approved_paths>
mypy <approved_paths>
```

Policy gate 会拒绝：

- shell metacharacters
- 绝对路径
- `..` 路径穿越
- `.env`、私钥、credentials、SSH 材料
- 看起来像命令的搜索词，例如 `python -c ...`、`bash -c ...`、`curl ...` 或 `docker ...`

## Workspace 处理

真实 workspace 不会以可写方式挂载。在 Docker 执行前，runner 会把仓库复制到临时目录，并排除：

- `.git`
- `.env`
- 私钥和 credential 文件
- 虚拟环境
- `node_modules`
- build 和 dist 输出
- cache 目录
- binary/archive 文件

临时副本会在执行结束后删除。

## Docker 设置

Docker 使用：

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

容器不会收到：

- `OPENAI_API_KEY`
- `VERIFIER_OPENAI_API_KEY`
- `GITHUB_TOKEN`
- 默认情况下的任何宿主机环境变量

## GitHub Actions 策略

`review-action` 读取：

```yaml
PR_AGENT_VERIFY_MODE: sandbox
PR_AGENT_VERIFY_MAX_FINDINGS: "3"
PR_AGENT_VERIFY_TIMEOUT_SECONDS: "45"
PR_AGENT_PUBLISH_POLICY: verified_or_high_confidence
```

Fork pull request 会自动从 `sandbox` 降级到 `static`。这可以避免默认在 CI 中执行不可信 fork 代码。

推荐行为：

| Event | Verification |
| --- | --- |
| same-repository pull request | static 或 sandbox |
| fork pull request | static only |
| push | static 或 sandbox |

## 剩余风险

Docker sandbox 能降低风险，但不是形式化安全证明。应保持较短 timeout，不要把 secrets 传入容器；除非 maintainer 明确修改策略，否则 fork PR 应保持 static verification。
