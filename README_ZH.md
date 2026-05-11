# Codex Red Team Opt-In Mode

[English](./README.md) | 中文

> **默认普通模式。只有在你明确武装时，才进入红队模式。**

这是一个面向 Codex 的**轻量级、阶段感知型红队配置层**。

它默认保持 **normal mode**，只有你显式开启时，才会进入 **red-team routing**。项目提供：

- opt-in 红队模式
- 轻量 hooks
- 结构化 JSON 模式状态
- 规则优先 + 语义兜底的 phase 检测
- 会话隔离状态
- 结构化红队任务编排
- 面向多阶段任务的 review gate

---

## 为什么做这个项目

很多“常驻红队提示词”最后都会变成两种坏结果：

1. **污染普通工作**
2. **注入过重，导致上下文膨胀**

这个项目反过来做：

- **普通模式保持普通**
- **红队模式必须显式开启**
- **hooks 保持轻量**
- **phase 路由保持克制**

---

## 功能特性

- **仅显式开启**
  - 默认是 normal mode
  - 必须显式开启才进入 red-team mode

- **阶段感知**
  - web
  - ad
  - postex
  - reverse
  - code-audit
  - payload

- **规则优先 + 语义兜底**
  - 明确命令与强特征优先命中
  - 对自然语言表达使用轻量语义兜底

- **会话隔离**
  - 一个会话不会覆盖另一个会话的模式状态

- **结构化任务编排层**
  - recon → strategy → exploit-dev → review → reporting
  - 结构化 artifact
  - review-before-delivery

- **跨平台安装**
  - Windows / macOS / Linux

- **可验证**
  - 安装验证
  - hook 验证
  - orchestration gate 验证
  - 普通模式洁净性验证

---

## 安装

### Python

```bash
python scripts/install.py
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

### macOS / Linux

```bash
python3 scripts/install.py
```

---

## 快速开始

### 开启红队模式

```text
进入红队模式
开启红队模式
/redteam on
enable red team mode
```

### 关闭红队模式

```text
退出红队模式
关闭红队模式
/redteam off
disable red team mode
```

### 验证安装

```bash
python scripts/validate.py
```

---

## 工作方式

### 1. 模式门控

项目默认处于 **normal** 模式。

除非你明确开启红队模式，否则：

- 不会注入 offensive doctrine
- 不会把普通任务强行解释成红队任务

### 2. 轻量 hooks

运行时 hook 刻意保持很小：

- SessionStart 注入短上下文
- 不做巨型 prompt 注入
- 不做 always-on offensive 偏置

### 3. Phase 检测

phase 检测**不是纯 regex**。

当前顺序是：

1. 显式规则优先
2. 轻量语义兜底

示例：

- `程序启动后会释放文件并拉起子进程，帮我梳理执行链` → `reverse`
- `帮我从入口一路追到危险函数，看看权限边界哪里失守` → `code-audit`
- `拿到 shell 之后下一步应该先做什么` → `postex`

### 4. 结构化任务编排

对于更大的任务，项目提供轻量编排层：

```text
recon -> strategy -> exploit-dev -> review -> reporting
```

注意：

- 这不是 always-on 自动攻击链
- 它是一个**结构化规划与 gate 框架**

---

## 仓库结构

```text
.github/
agents/
  skills/
    red-team-command-doctrine/
codex/
  AGENTS.md
  hooks/
  orchestrator/
docs/
scripts/
templates/
tests/
```

---

## 验证内容

当前项目会验证：

- 模式开启/关闭
- phase 路由
- 语义 fallback
- 普通模式洁净性
- 会话隔离
- orchestration gates

---

## 当前限制

- 它是一个**控制层 / 配置层**，不是完整攻击平台
- 不包含 RAG 或私有知识库检索
- `redteam-light` 与 `redteam-full` 目前行为还未拉开
- 实际执行深度仍依赖你的 MCP / 工具面

---
## ⚠️ 免责声明 / Disclaimer

**本项目仅供授权渗透测试（Authorized Penetration Testing）和安全研究使用。**

### 重要声明
- 本工具 **仅限** 在您拥有 **明确书面授权** 的目标系统或环境中使用。
- 未经授权擅自用于任何生产系统、他人资产或非授权目标，属于违法行为，作者及贡献者不承担任何责任。
- 使用本项目即表示您同意自行承担所有风险，包括但不限于法律责任、数据泄露、系统损坏等后果。
- 作者及本项目不提供任何明示或暗示的担保，包括但不限于适销性、特定用途适用性及不侵权。

### Legal & Ethical Use Only
This project is intended **solely for educational purposes, authorized red team operations, and legal penetration testing** where you have explicit permission from the system owner.

- Any unauthorized use, including but not limited to attacking systems without consent, is strictly prohibited.
- The authors and contributors assume **no liability** for any damages, legal consequences, or losses resulting from the use or misuse of this tool.
- Users are fully responsible for ensuring their activities comply with all applicable local, national, and international laws.

**继续使用本项目 = 您已阅读、理解并同意以上全部条款。**

---

**如果您无法确保合法授权，请立即停止使用本项目。**
不需要回复，我存一下免责声明
## 贡献

见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 许可证

MIT + authorized-use-only notice。  
见 [LICENSE](./LICENSE)。
