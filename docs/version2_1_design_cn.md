# Version 2.1 设计报告

[English version](version2_1_design.md)

## 定位

Version 2.1 将项目从“只依赖 LLM 的 PR reviewer”升级为“证据验证型 review harness”。

旧的 v2.0 流程是：

```text
Reviewer -> Validator -> Report
```

v2.1 流程是：

```text
Reviewer
  -> Verification Planner
  -> Policy Gate
  -> Tool Executor
  -> Evidence Adjudicator
  -> Publisher Gate
  -> Report
```

目标不是做 autonomous coding agent，而是降低误报，并让每个重要 finding 都说明是否被验证、使用了什么工具、收集了什么证据，以及这些证据如何影响最终发布决策。

## 系统架构

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

Reviewer 仍然负责读取 diff 和仓库上下文，并生成候选 finding。在 multi-agent 模式下，Bug、Test、Security、Performance reviewer 会分别运行，然后由确定性 coordinator 协调。

Reviewer 输出被刻意限制：

- 可以描述怀疑的问题。
- 可以建议验证意图，例如搜索词或可能的测试文件。
- 不能提供原始 shell 命令。
- 不能提供 Docker 参数。
- 不能请求网络访问。

输出会被解析成结构化 schema，并在验证开始前继续经过已有 validator。

### Verification Planner

Verification Planner 将候选 finding 转成保守的 `VerificationPlan`。

计划包含：

- `finding_id`
- 验证目标
- 请求的工具类型
- 搜索词
- 候选测试路径
- rationale
- risk level

Planner 同时使用模型提供的 verification intent 和确定性默认策略。finding 类别会强烈影响工具选择：

| Finding 类别 | 典型工具 |
| --- | --- |
| Bug | repository search, read file, test discovery, pytest, ruff, mypy |
| Test | repository search, test discovery, pytest |
| Security | repository search, read file, dependency inspection, ruff |
| Performance | repository search, read file, test discovery |

Planner 不被信任为 executor。它的输出只是建议，必须经过 Policy Gate。

### Policy Gate

Policy Gate 是确定性的。它根据当前 finding、mode、workspace、path 和 risk level 决定请求的工具是否允许。

它强制：

- verification mode：`off`、`static`、`sandbox`
- 类别到工具的 allowlist
- 路径 allowlist 和 deny-list
- 敏感文件阻断
- 搜索词清洗
- sandbox eligibility
- budget 和 timeout 限制

最重要的设计规则：模型永远不能直接运行命令。系统只能从预定义工具实现和命令模板中选择。

### Tool Executor

Tool Executor 运行经过批准的工具，并记录紧凑的 `ToolResult`。完整日志写到 artifact 文件，不塞进 `review_result.json`。

工具分两类：

- **Static tools**：只读仓库检查。
- **Sandbox tools**：在受限 Docker 容器中执行白名单检查。

Static tools 可用于 `static` 和 `sandbox` 模式。Sandbox tools 只在 `sandbox` 模式可用，并且只适用于本地/可信 workspace。

### Evidence Adjudicator

Evidence Adjudicator 接收：

- 原始 finding
- 被批准的 verification plan
- 收集到的 tool results

它返回 finding 级 verification record：

- status：`supported`、`contradicted`、`inconclusive`、`skipped` 或 `error`
- evidence summary
- confidence before/after
- publication decision
- 紧凑工具结果摘要

裁决必须保守。缺少证据不等于 finding 是假的；不相关测试通过也不能反驳 bug 报告。

## 工具系统设计

### `repository_search`

用途：

- 在本地 workspace 中搜索与 finding 相关的 symbol、function、class、配置项、错误名或 API 名。

输入：

- repository root
- 清洗后的 search terms
- 文件数量、单文件大小、结果数量限制

输出：

- 匹配路径
- 匹配行号
- 简短摘要
- 包含详细匹配的 artifact 文件

限制：

- 跳过 `.git`、虚拟环境、`node_modules`、build 输出、二进制文件和压缩包
- 拒绝敏感文件，例如 `.env`、私钥、credentials、SSH 材料
- 不访问网络

典型用途：

- 找可能不安全函数的调用点。
- 检查模型声称缺失的 helper 或 config 是否已经存在。
- 围绕变更 symbol 收集静态证据。

### `test_discovery`

用途：

- 找与变更文件或 finding 相关的候选测试。

输入：

- changed file path
- finding file path
- candidate test paths
- function name 等搜索词

规则：

```text
src/foo/bar.py
  -> tests/test_bar.py
  -> tests/foo/test_bar.py
  -> src/foo/test_bar.py
  -> 包含 "bar" 或相关函数名的文件
```

输出：

- candidate test paths
- confidence/reason summary
- discovery 详情 artifact 文件

典型用途：

- 当模型说“没有相关测试”时，用已有测试反驳 broad claim。
- 在 sandbox 模式下选择最小 pytest target。

### `pytest` Runner

用途：

- 运行与 finding 直接相关的 Python 定向测试。

允许的命令模板：

```text
python -m pytest -q <approved_test_path>
python -m pytest -q <approved_test_path>::<approved_test_name>
```

限制：

- 禁止任意 `python -c`
- 禁止 `pip install`
- 禁止 shell wrapping
- 只允许 approved paths
- 只在 sandbox 模式可用

解释：

- 失败的定向回归测试可以支持 finding。
- 通过的不相关测试不能反驳 finding。
- collection failure 或 missing dependency 通常给出 `inconclusive` 或 `error`。

### `ruff` Runner

用途：

- 在 approved paths 上运行白名单静态 lint 检查。

允许的命令模板：

```text
ruff check <approved_paths>
```

典型用途：

- 当仓库有 ruff 时，捕获语法错误、import 问题或简单静态问题。
- 为部分 bug 或 security finding 提供支持证据。

限制：

- 不允许 auto-fix mode
- 不允许模型指定任意 config path
- 只在 sandbox 模式可用

### `mypy` Runner

用途：

- 在 type checking 有价值且仓库已配置时，对 approved paths 做类型检查。

允许的命令模板：

```text
mypy <approved_paths>
```

典型用途：

- 支持 optional value、return type、argument mismatch 或 API contract break 相关 finding。

限制：

- 只在 sandbox 模式可用
- 有 timeout 限制
- 只允许 approved paths
- 缺少 type dependency 时，除非它直接支持 finding，否则视为 inconclusive

## 安全模型

### 只允许白名单命令

Executor 永远不接受模型给出的原始命令。它只把 approved tool kind 映射到固定命令模板。

允许的 sandbox command family：

```text
python -m pytest -q ...
ruff check ...
mypy ...
```

其他命令默认拒绝。

### 禁止任意 Shell

系统拒绝：

- `bash -c`
- `sh -c`
- `cmd /c`
- `powershell -Command`
- `python -c`
- shell metacharacters
- pipe 和 redirection
- chained commands
- install scripts
- `curl` 或 `wget` 等网络下载命令

### 无网络

Sandbox Docker 使用：

```text
--network none
```

这阻止测试或被审查代码访问 package registry、metadata endpoint、外部服务或攻击者控制的 host。

### Docker 隔离

执行前，workspace 会被复制到清理后的临时目录。真实用户 workspace 不会以可写方式挂载。

清理后的副本排除：

- `.git`
- `.env`
- 私钥
- credential 文件
- 虚拟环境
- `node_modules`
- build 输出
- cache 目录
- binary/archive 文件

Docker 设置包括：

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

`OPENAI_API_KEY`、`VERIFIER_OPENAI_API_KEY`、`GITHUB_TOKEN` 等 secrets 不会传入容器。

## 验证逻辑

### `supported`

当工具证据直接支持 finding 时，状态为 supported。

例子：

- 定向 pytest 抛出了 finding 描述的确切异常。
- 静态搜索找到调用点，证明不安全路径可达。
- 静态检查器报告了 finding 描述的相同行或 symbol。

默认决策：

```text
status = supported
confidence_after = min(confidence_before + 0.10, 0.99)
publication_decision = publish
```

### `contradicted`

当证据直接反驳 finding 时，状态为 contradicted。

例子：

- 模型声称没有相关测试，但 `test_discovery` 找到了覆盖该行为的相关测试。
- 模型声称某值可能为 `None`，但仓库搜索显示所有调用方都会在调用前校验。
- 模型报告缺少依赖，但 dependency inspection 显示该依赖已声明。

默认决策：

```text
status = contradicted
confidence_after = 0.0
publication_decision = suppress
```

### `inconclusive`

当工具无法证明或反驳 finding 时，状态为 inconclusive。

例子：

- 不存在相关测试。
- 测试通过，但没有覆盖 finding 描述的具体分支。
- 静态搜索找到了 symbol，但没有足够 call-path 证据。
- sandbox 因缺少依赖无法运行。

默认决策：

```text
status = inconclusive
confidence_after = max(confidence_before - 0.10, 0.0)
publication_decision = publish_with_warning or suppress
```

高严重性、高置信度 finding 仍可带警告发布。中低信号 finding 更倾向于被抑制，以减少评论噪音。

## 失败场景

### Flaky Test

Flaky test failure 不应自动支持 finding。

处理方式：

- 将 tool result 标记为 failed 或 inconclusive。
- 记录失败摘要和日志路径。
- 除非 failure stack 明确映射到 finding 和 changed line，否则倾向于 `inconclusive`。
- 不要把通用 flaky failure 转成高置信 bug report。

### Unrelated Pytest Failure

不相关 pytest failure 不应支持或反驳 finding。

处理方式：

- 如果失败测试没有覆盖 changed code 或 finding 描述的行为，证据为 `inconclusive`。
- 保留日志 artifact 以便追踪。
- 不要因为无关测试失败而 suppress finding。

### Missing Dependency

Sandbox 或极简 CI 环境中经常缺少依赖。

处理方式：

- 如果 dependency inspection 显示 pytest/ruff/mypy 不可用，则跳过该执行工具。
- Static tools 仍然可以运行。
- 将 finding 标记为 `inconclusive`，而不是 `contradicted`。
- 只有工具调用本身发生非预期失败时才用 `error`。

## 输出

普通 review 输出：

- `review_result.json`
- `review_report.md`
- `trace.jsonl`

v2.1 verification 输出：

- `verification_report.json`
- `artifacts/verification/<finding-id>/search_result.json`
- `artifacts/verification/<finding-id>/test_discovery.json`
- `artifacts/verification/<finding-id>/tool_result.json`
- sandbox 日志，例如 `pytest.log`、`ruff.log`、`mypy.log`

## 兼容性

`--verify off` 是默认值，保持 v2.0 行为。Verification 字段都是可选的，因此已有 review JSON 仍然可读。
