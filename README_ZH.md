# Codex 红队模式

一个适配 Codex App 与 Codex CLI 的、显式开启的持久化红队执行运行时。

项目会把用户目标编译为带目标级成功准则的类型化 `GoalContract`，通过真实 MCP 工具执行单领域、跨领域或多目标批次 `WorkflowSpec`，保存证据图，支持中断恢复，并且只在 `TerminalJudge` 证明全部准则后进入完成状态。

## 核心重构

运行时已经移除 `phase -> router -> pack -> leaf`、正则领域路由、Markdown ExitGate 和第二套 Automation 状态机。原 36 张领域卡被一张仅描述边界的卡替代：

```text
GoalContract
  -> WorkflowSpec
  -> Durable Scheduler
  -> ToolBroker
  -> SemanticVerifier
  -> EvidenceGraph
  -> TerminalJudge
```

## 主要能力

- **显式开启**：默认始终为 normal 模式。
- **系统层提示词**：通过 `model_instructions_file` 加载基础指令和对应模型 profile。
- **类型化工作流**：八个 TOML 工作流覆盖 Web/API、外网面、源码、二进制/移动端、身份/云、对抗模拟、模型安全和通用自适应任务。
- **真实 MCP 发现**：支持 stdio 与 Streamable HTTP，通过 `initialize` 和 `tools/list` 获取工具。
- **互补工具集成**：发现阶段可有界调用多个能力互补的 MCP；验证阶段保持单路径优先。
- **持久执行**：SQLite WAL、事件、租约、幂等结果和证据能够跨会话恢复。
- **无需用户搬运结果**：仅在 App 当前 Agent 独占某工具时，由 Agent 自动调用并通过 `redteam_run.observation/observations` 回传。
- **语义证据**：用户文字、文件名、报告文字和工具 success 字段不等于漏洞证明。
- **严格终态**：必需动作、目标覆盖、证据血缘、复现、影响、覆盖检查、回滚和报告必须全部通过。
- **批次自治**：多目标任务拥有独立工作流和 run ID，同时支持统一恢复、Host 回灌、终态和取消。

## 安装

```bash
python -m pip install -r requirements.txt
python scripts/install.py --model gpt-5.6-sol
```

项目级安装：

```bash
python scripts/install.py --project-home PATH --model gpt-5.6-sol
```

自定义 Skill 目录：

```bash
python scripts/install.py --project-home PATH --agents-home AGENTS_PATH --enable-custom-skill-dirs --model gpt-5.6-sol
```

自定义持久 operation 目录：

```bash
python scripts/install.py --project-home PATH --log-root OPERATION_PATH --model gpt-5.6-sol
```

安装器会先部署候选版本并进行操作级验证，成功后才提交 manifest；失败时保留事务状态用于恢复和清理。

## 配置写入

安装器保留用户已有配置，并管理以下字段：

```toml
model_instructions_file = './redteam-mode/system-instructions.md'

[features]
hooks = true
automation = true

[automation]
mode = "active"
max_actions_per_cycle = 16
action_timeout_seconds = 60
max_retries_per_action = 2
max_domains = 7
max_hypothesis_branches = 4
persist_run_state = true

# 可选：为名称/描述不透明的外部 MCP 显式声明能力
# [automation.tool_capabilities]
# "server:tool" = ["page_fetch", "controlled_validation"]

[mcp_servers.codex-redteam-runtime]
command = "PYTHON_EXECUTABLE"
args = ["-m", "runtime.mcp_server", "--root", "OPERATIONS_ROOT"]
enabled = true

[mcp_servers.codex-redteam-runtime.env]
PYTHONPATH = "CODEX_HOME"
CODEX_HOME = "CODEX_HOME"
```

安装器不会写入 `preauthorized_targets`。

## App 使用流程

1. 安装后重启 Codex App。
2. 新建任务，单独输入 `/redteam on`、`/redteam light` 或 `/redteam full`。
3. 输入完整操作目标。
4. Hook 将目标编译成 GoalContract，保留跨领域提示或将多目标分配到独立 operation。
5. `redteam_run` 自动调用可用 MCP 工具；发现阶段最多组合三个互补工具结果。
6. 如果某能力只存在于当前 App Agent，系统上下文会给出 phase/trigger/feedback gate/exit condition/output contract，由 Agent 直接执行并回灌。
7. Runtime 每次转换都会把 run ID、待执行动作、artifact 和终态同步到 Hook 会话状态，新会话恢复不需要用户复制结果。
8. TerminalJudge 仅在每个目标/领域准则都有复现、影响、覆盖和清理血缘时返回成功报告。

新建 App 任务会重新加载 `model_instructions_file`。静态 system catalog 根据 Hook 提供的模型元数据选择对应 profile，不把 profile 注入用户提示词。

## CLI 使用流程

普通 CLI 会话使用同一套系统提示词、Hooks、MCP runtime 和模式命令。

可选 wrapper 会锁定单个模型族 system profile：

```bash
codex-redteam --model gpt-5.6-sol
```

Wrapper 创建临时单 profile 系统指令文件，Codex 退出后自动删除；切换模型族需要重新启动 wrapper。

## MCP 工具

| 工具 | 用途 |
|---|---|
| `redteam_run` | 单一自主入口：启动/恢复单次或批次 operation，并接收 Host observations |
| `redteam_start` | 编译并启动新 operation |
| `redteam_resume` | 继续持久 operation |
| `redteam_status` | 返回动作、证据和缺失谓词 |
| `redteam_submit_observation` | 对 Host Agent 工具结果执行语义校验并回灌 |
| `redteam_evidence` | 按 ID 获取 compact status 中省略的已验证 payload |
| `redteam_cancel` | 取消单次或整个批次 operation，并持久化每条清理状态 |
| `redteam_events` | 按游标返回追加式 operation 事件链 |

Runtime 发现下游 MCP 时会排除自身，避免递归调用。

## 工作流模型

每个 `codex/workflows/*.toml` 声明：

- 工作流 ID 与版本
- 语义匹配标签
- 类型化动作及依赖
- 可替代工具能力
- 期望 artifact 与 verifier
- 风险、超时、重试和回滚动作
- 工具策略、阶段、触发条件、反馈 gate 和退出条件
- 终态谓词和必需 artifact

领域只作为 ATT&CK/资产/技术标签，不再控制运行时分支。

## 证据模型

每个证据节点包含 operation/action ID、目标、工具、artifact 类型、语义校验器、原始结构化输出、SHA-256、父证据、置信度和时间戳。Evidence schema v2 允许不同工具产生内容相同但 provenance 独立的证据，并自动迁移旧数据库和 artifact 文件名。

派生证据必须引用可信父节点；复现要求具体重放数据，影响要求已测量结果，覆盖报告要求负对照，清理证明要求验证回滚状态。

## 持久化

Operation 默认存储在 `$CODEX_HOME/redteam-mode/operations`，可通过安装器的 `--log-root` 指定其他目录。

```text
runtime.sqlite3
artifacts/<run-id>/*.json
```

SQLite 使用 WAL 和显式 schema 版本。Operation lease 串行化调度器，Action lease 保护单次调用，确定性 idempotency key 防止恢复后重复产生副作用；工作流版本与指纹绑定会拒绝静默漂移。

多目标 operation 使用绑定父会话、目标和目标文本的确定性 batch ID；相同父会话中的新目标不会混入旧批次。Runtime 与 App/CLI Hook 通过共享跨进程锁串行化完整状态更新，再原子替换 `$CODEX_HOME/redteam-mode/state/sessions` 中的会话文件。

缺少目标的 Goal 会在执行前返回 `waiting_goal_input`。Goal、事件、结果和证据在持久化前递归脱敏，单个证据上限为 4 MiB；POSIX 下运行时目录和文件使用私有权限。

Status 只内联不超过 64 KiB 的证据 payload；更大的节点保留元数据，并可通过 `redteam_evidence` 按需获取，避免常规 App/CLI 上下文膨胀。

## 唯一边界卡

只安装 `agents/skills/redteam-boundary-policy/SKILL.md`。它只约束证据真实性、目标/会话绑定、秘密处理、可回滚执行和工具 handoff。

它不参与路由，也不参与 TerminalJudge。

## 验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/validate.py --codex-home .
```

Validator 会实际启动 MCP server 自检并加载八个工作流。测试覆盖假终态、伪证拒绝、并发启动/恢复、可执行 Host Agent handoff、取消清理、秘密脱敏、工作流漂移、真实 stdio/HTTP MCP、事务安装、App/CLI Hook 和卸载保护。

## 卸载

```bash
python scripts/install.py --uninstall
python scripts/install.py --project-home PATH --uninstall
```

只删除 manifest 管理的文件和配置/Hook 字段；用户自行修改的配置、提示词、Hook 与 AGENTS 内容会保留。

## 目录

```text
codex/runtime/       持久 operation 引擎与 MCP server
codex/workflows/     类型化工作流
codex/hooks/         App/CLI 生命周期桥接
codex/prompts/       模型专用 system profile
agents/skills/       唯一边界策略卡
scripts/             事务安装器和 validator
tests/               Runtime、对抗、Hook 与安装测试
```

模型能力释放、专业红队工作流和起点到终态自动化的验收标准见 `CAPABILITY_ACCEPTANCE.md`。
