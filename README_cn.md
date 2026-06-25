# AI PR Review Agent

[English version](README.md)

AI PR Review Agent 是一个本地优先的代码审查 harness，支持 GitHub Pull Request、commit、compare range 和本地 diff。它会把不同来源的变更统一成 `ChangeSet`，检索轻量仓库上下文，运行多类专门 reviewer，校验结构化 finding，并生成可复现的 JSON、Markdown、trace 和 verification artifact。

这个项目不是通用自动编码 Agent。它的定位是受控代码审查系统：模型负责提出候选问题，harness 负责目标加载、上下文构造、结果校验、证据收集、报告生成和安全边界。

## Version 2.1 - 证据验证型 Agent

### 问题背景

只靠 LLM 做 PR review 有三个常见问题：

- **幻觉**：模型可能推断出仓库里并不存在的行为。
- **假阳性**：看起来合理的问题会变成噪音 PR 评论。
- **缺少验证链路**：finding 往往说不清用了什么工具、收集了什么证据、证据到底支持还是反驳它。

v2.1 在候选 finding 之后加入了一层受控验证流程。

### 核心思路

```text
候选 Finding
    |
    v
验证计划
    |
    v
策略门禁
    |
    v
工具执行
    |
    v
证据裁决
    |
    v
最终发布决策
```

Reviewer 可以提出验证意图，但不能执行任意命令。系统由确定性 policy 决定哪些工具可用，再由 executor 收集有限证据，最后由 evidence adjudicator 判断证据是支持、反驳，还是无法确认 finding。

### 三种验证模式

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `off` | 不运行验证工具，保持 v2.0 行为。 | 快速 review、基线对比、低风险场景。 |
| `static` | 只运行只读工具，例如仓库搜索、文件读取、测试发现、依赖检查。 | 默认安全模式，适合本地和 CI，也适合 fork PR。 |
| `sandbox` | 在 static 基础上，允许 Docker 中运行白名单检查，例如定向 `pytest`、`ruff`、`mypy`。 | 本地 workspace 或可信 CI checkout，且允许执行代码。 |

### 三种验证结果

| 结果 | 含义 | 发布影响 |
| --- | --- | --- |
| `supported` | 工具证据明确支持 finding，例如定向测试在变更行失败。 | 发布，并可能提高置信度。 |
| `contradicted` | 工具证据明确反驳 finding，例如模型说缺测试，但已有测试覆盖该行为。 | 抑制该 finding。 |
| `inconclusive` | 工具证据不足，既不能确认也不能否定。测试通过也不能直接证明 bug 不存在。 | 根据严重程度和策略，带警告发布或抑制。 |

### 简单端到端例子

候选 finding：

```text
src/profile.py 可能存在 None dereference：在检查 user is None 之前读取了 user.display_name。
```

验证流程：

```text
1. 验证计划
   目标：确认 None 输入路径是否不安全。
   工具：repository_search、test_discovery、pytest。

2. 策略门禁
   static 模式允许 repository_search 和 test_discovery。
   sandbox 模式只允许对批准的测试路径运行定向 pytest。

3. 工具执行
   repository_search 找到 display_name 调用点。
   test_discovery 找到 tests/test_profile.py。
   pytest 运行 python -m pytest -q tests/test_profile.py::test_display_name_none。

4. 证据裁决
   如果 pytest 在变更行抛出 AttributeError：
     status = supported
     decision = publish
   如果已有测试证明 None 路径已被正确 guard：
     status = contradicted
     decision = suppress
   如果找不到相关测试：
     status = inconclusive
     decision = publish_with_warning 或按策略 suppress
```

### 相比 v2.0 的变化

- 新增 finding 级别的验证计划、工具结果、证据摘要、置信度变化和发布决策。
- 新增确定性 policy gate，避免 LLM 直接运行 shell 命令。
- 新增 static 工具：仓库搜索、文件读取、测试发现、依赖检查。
- 新增 Docker sandbox 工具执行，限制为白名单命令、无网络、无 secrets。
- 新增 `verification_report.json` 和 `artifacts/verification/<finding-id>/...` 输出。
- 新增 evidence adjudication，支持 `supported`、`contradicted`、`inconclusive`。
- 新增发布门禁，被反驳或弱证据的 finding 可以被抑制。
- 新增 live E2E case 和人工判断报告，覆盖 Python 与 C++。

### Review 命令

```powershell
pr-agent review local `
  --out outputs/local-review `
  --verify static `
  --workspace . `
  --verification-budget 3 `
  --verification-timeout 45
```

独立验证已有结果：

```powershell
pr-agent verify outputs/local-review/review_result.json --workspace . --mode static --out outputs/verified-review
```

### v2.1 输出文件

- `review_result.json`：结构化审查结果，包含 finding 级 verification 数据。
- `review_report.md`：人类可读 Markdown 报告。
- `trace.jsonl`：review 与 verification trace。
- `verification_report.json`：验证指标和逐 finding 记录。
- `artifacts/verification/<finding-id>/search_result.json`：仓库搜索证据。
- `artifacts/verification/<finding-id>/test_discovery.json`：相关测试发现证据。
- `artifacts/verification/<finding-id>/pytest.log`：sandbox 模式下的测试日志。

### 扩展 Live E2E 人工评估

运行命令：

```powershell
python -m pr_agent.main run-live-e2e --cases evaluation/live_e2e_cases.jsonl --out outputs/live-e2e-expanded --verify static --verification-budget 3 --verification-timeout 45
```

摘要：

- 数据集：20 条 case，覆盖 Python + C++。
- 主跑：19 条完成，1 条 provider 断连（`LIVE017`）。
- 重试：`LIVE017` 单独重试完成。
- 验证模式：`static`，多数 verification 结果预期为 `inconclusive`。
- 详细报告：`outputs/live-e2e-expanded/manual_judgement_report.md`。

| Case | 类型 | 预期 | 人工结果 |
| --- | --- | --- | --- |
| LIVE001 | Python bug | None guard 前访问属性 | 扫出；有相关测试噪音 |
| LIVE002 | Python security | f-string SQL 注入 | 扫出；重复 security finding 被抑制 |
| LIVE003 | Python security | Authorization token 日志泄露 | 扫出；有测试噪音 |
| LIVE004 | Python mixed | Unsafe YAML + N+1 查询 | 两个都扫出；没有误报 SQL |
| LIVE005 | Python clean | 参数化 SQL 不应报错 | 干净 |
| LIVE006 | Python clean | 保留 None guard，不应误报 None dereference | 避免目标误报，但有测试/契约噪音 |
| LIVE007 | Python clean/tests | 已有测试应抑制广义缺测试评论 | 干净；证据门禁抑制候选 finding |
| LIVE008 | Python performance | cache 关闭依赖 benchmark | 谨慎性能警告；static 证据不确定 |
| LIVE009 | Python blocker | SyntaxError/import blocker | 扫出 |
| LIVE010 | Python conditional crash | `total == 0` 除零 | 扫出；有测试噪音 |
| LIVE011 | Python logic/security | 权限 owner 判断反转 | 扫出；bug/security/test 重复噪音 |
| LIVE012 | Python concurrency | 移除 lock 导致 race/lost update | 扫出；static 证据不确定 |
| LIVE013 | Python resource leak | 文件句柄泄漏 | 扫出；bug/security/test 分类噪音 |
| LIVE014 | Python clean concurrency | lock 保留，应干净 | 干净；低价值测试候选被抑制 |
| LIVE015 | C++ blocker | 缺分号导致编译失败 | 扫出 |
| LIVE016 | C++ conditional crash | nullptr guard 前解引用 | 扫出；有测试噪音 |
| LIVE017 | C++ lifetime | 返回 dangling `c_str()` 指针 | 部分成功；重试完成，根因被提到，但公开 finding 只是测试 finding |
| LIVE018 | C++ memory | early return 内存泄漏 | 部分成功；识别根因，但公开 finding 只是测试 finding |
| LIVE019 | C++ concurrency | 移除 mutex 导致 data race | 扫出；static 证据不确定 |
| LIVE020 | C++ clean RAII | RAII ownership 不应误报内存问题 | 避免 memory/pointer 误报，但有测试噪音 |

人工结论：agent 对明显崩溃、构建失败、安全、逻辑和移除锁的问题，在 Python 与 C++ 上表现不错。主要弱点是发布质量：重复根因、test-review 噪音，以及 C++ memory/lifetime bug 有时只以“缺测试”形式公开。

## Version 2.0 更新

v2.0 把单次泛化审查升级成多 reviewer 协同审查：

- **多 Agent reviewer**：Bug、Test、Security、Performance reviewer 分别做专门审查。
- **Coordinator**：确定性协调器负责去重和排序。
- **Patch suggestion**：finding 可包含结构化修复计划和可选 patch。
- **Test suggestion**：finding 可包含测试场景、断言和可选测试代码。
- **PR 级评测**：`eval-report` 衡量有效 finding、假阳性、行命中、可修复性、延迟和 token 使用。

## Version 1 更新

Version 1 将 MVP 扩展成更完整的工程化 harness：

- 支持 GitHub PR URL、commit URL、compare URL 和本地 diff。
- 引入 `ReviewTargetInfo`、`ReviewTargetRef`、`ChangeSet` 等统一模型。
- 新增 GitHub Actions 审查和 summary comment。
- 新增本地 diff 解析和示例输出。
- 新增评测数据集和 schema 校验。
- 改进 JSON 恢复、环境变量加载、trace 和 token 统计。

## 核心能力

- **统一 review 命令**：`pr-agent review <target>` 支持 PR、commit、compare 和 local。
- **目标自动识别**：识别 GitHub PR、commit、compare URL 和 `local`。
- **统一 ChangeSet 抽象**：规范化 target metadata、changed files 和 parsed hunks。
- **Unified diff 解析**：跟踪 changed line 的 old/new line number。
- **仓库上下文检索**：同文件周边代码、README 摘要、相关测试候选。
- **多 Agent 审查**：Bug、Test、Security、Performance reviewer。
- **结构化 finding**：使用 Pydantic schema，便于后续处理。
- **质量门禁**：置信度、文件路径、行号、确定性假阳性过滤和可选 LLM verifier。
- **Markdown 与 JSON 报告**：生成可复现本地 artifact。
- **GitHub Actions 支持**：自动审查并发布 summary comment。
- **评测 harness**：标签数据集、可运行 PR case、verification case 和 live E2E case。

## 架构

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

## 快速开始

创建并安装虚拟环境：

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
```

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

运行 review：

```powershell
# GitHub PR
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/pull/123 --out outputs/pr-review

# GitHub commit
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/commit/<sha> --out outputs/commit-review

# GitHub compare range
.\.venv-win\Scripts\pr-agent.exe review https://github.com/owner/repo/compare/main...feature --out outputs/compare-review

# 本地 diff
.\.venv-win\Scripts\pr-agent.exe review local --out outputs/local-review --verify static --workspace .
```

只抓取 metadata 和解析 diff：

```powershell
.\.venv-win\Scripts\pr-agent.exe fetch local --out outputs/local-fetch
```

## CLI 命令

| 命令 | 用途 |
| --- | --- |
| `fetch <target>` | 加载 target metadata 和 changed files，但不运行 review。 |
| `review <target>` | 运行完整 review pipeline，输出 JSON、Markdown 和 trace。 |
| `verify <review_result.json>` | 对已有 review_result 中的 finding 做验证。 |
| `review-action` | 解析 GitHub Actions event 并发布 summary comment。 |
| `eval-dataset` | 校验标签评测数据集。 |
| `eval-report` | 基于 case 和 prediction 生成 PR 级评测指标。 |
| `eval-verification` | 汇总 verification evaluation case。 |
| `eval-run` | 用 deterministic 或 live LLM 运行可执行 PR case。 |
| `run-live-e2e` | 运行 live LLM E2E case，输出供人工判断。 |

## 测试与评测

运行单元测试：

```powershell
pytest
```

运行 verification case 汇总：

```powershell
python -m pr_agent.main eval-verification --cases evaluation/verification_cases.jsonl --out outputs/verification-eval.json
```

运行 live E2E：

```powershell
python -m pr_agent.main run-live-e2e --cases evaluation/live_e2e_cases.jsonl --out outputs/live-e2e --verify static
```

评测 artifact 包括：

- `evaluation/cases.jsonl`：parser、schema、filter 和 issue-detection case。
- `evaluation/pr_cases.jsonl`：PR 级评测 case。
- `evaluation/verification_cases.jsonl`：v2.1 verification status case。
- `evaluation/live_e2e_cases.jsonl`：用于人工判断的 live LLM E2E case。
- `examples/evaluation/run/`：deterministic runnable evaluation 输出。

## 安全边界

- LLM 永远不能直接执行任意 shell 命令。
- static verification 只读。
- sandbox mode 只运行白名单命令模板。
- Docker sandbox 无网络、无 secrets、降低 capabilities、限制资源，并使用清理后的临时 workspace 副本。
- GitHub Actions 中 fork PR 默认降级为 static verification。
- Agent 不修改源码、不提交、不 push、不自动应用 patch。

## 示例输出

Review 输出包括：

- `review_result.json`
- `review_report.md`
- `trace.jsonl`
- `verification_report.json`
- `artifacts/verification/...`

示例目录：

- `examples/octocat_hello_world/`
- `examples/octocat_commit/`
- `examples/octocat_compare/`
- `examples/evaluation/run/`
- `outputs/live-e2e-expanded/`

## 文档

- [Version 2.0 design](docs/version2-design.md)
- [Version 2.1 design](docs/version2_1_design.md)
- [Sandbox security](docs/sandbox-security.md)
- [Verification evaluation](docs/verification-evaluation.md)
- [Agent harness design](docs/agent-harness-design.md)
