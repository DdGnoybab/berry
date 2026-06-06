# Berry

> 接入飞书的编码 Agent 后端。
> 灵感来源：Claude Code / Claw Code，做成飞书原生体验。

---

## 这是什么

Berry 是一个通用的交互式 AI 助手 runtime，接入飞书机器人。核心设计：

```
通用 runtime（turn loop + 工具分发 + 审批）
  + Skill 工具（markdown → context 注入）
  + System prompt（身份 + 行为边界）
  + 飞书 channel（WS 长连 + 卡片交互）
  = 一个可以做任何事的飞书 agent
```

**设计哲学**：
- Runtime 是通用的——不包含任何业务逻辑
- Skill 是 markdown 文件——描述行为准则，LLM 按指引执行
- Todo 是通用进度追踪工具——业务逻辑全在 Skill 里
- 新增场景 = 新增一个 `.berry/skills/<name>/SKILL.md`，不碰 runtime 代码

---

## 当前状态

| 模块 | 状态 |
|------|------|
| Turn loop（ConversationRuntime） | ✅ |
| LLM Gateway（Anthropic / OpenAI / DeepSeek） | ✅ |
| Stream Accumulator | ✅ |
| Tool Protocol + Registry | ✅ |
| 11 个 LLM 工具（bash / read / write / edit / grep / glob / web_search / web_fetch / todo_write / todo_read / skill） | ✅ |
| Todo 系统（对齐 claw-code + 飞书可视化 + nag reminder） | ✅ |
| Approval model（Policy + Channel） | ✅ |
| System Prompt Builder + skill 发现 | ✅ |
| Skill 工具 | ✅ |
| Session persistence（文件系统） | ✅ |
| DB（PostgreSQL + alembic） | ✅ |
| 飞书 channel（WS 长连 + 消息处理 + 审批卡片 + Typing 表情） | ✅ |
| CLI entrypoint + REPL | ✅ |

---

## 架构

```
berry/
├── core/                     通用 AI 能力（runtime 层）
│   ├── agent/                Turn loop / prompt / session / approval / todo_event
│   ├── llm/                  Gateway + adapters（Anthropic / OpenAI）
│   ├── tools/                Tool 实现
│   │   ├── core/
│   │   │   ├── skill.py      Skill 工具
│   │   │   └── todo.py       Todo 工具（对齐 claw-code）
│   │   ├── files/            read / write / edit
│   │   └── web/              search / fetch
│   ├── db/                   PostgreSQL + repos
│   └── project/              Workspace 管理
├── channels/
│   ├── feishu/               飞书 channel（28 个文件）
│   │   ├── bot.py            主编排
│   │   ├── todo_card.py      Todo 进度卡片渲染
│   │   ├── reaction.py       Typing 表情
│   │   └── ...
│   └── cli/                  CLI REPL
├── entrypoints/
│   ├── feishu.py             飞书入口（WS 长连）
│   └── cli.py                CLI 入口
├── gateway/                  Method registry
├── security/                 安全策略
└── .berry/skills/            Skill 定义（markdown）
```

**依赖方向**：`entrypoints → channels/gateway → core`。Core 不知道有什么 channel 或什么 skill。

---

## Todo 系统

Todo 是通用进度追踪工具，对齐 claw-code TodoWrite：

```python
todo_write(todos=[
    {"content": "步骤1", "activeForm": "正在做步骤1", "status": "completed"},
    {"content": "步骤2", "activeForm": "正在做步骤2", "status": "in_progress"},
    {"content": "步骤3", "activeForm": "等待中", "status": "pending"},
])
```

**飞书可视化**：每次 `todo_write` 调用 → 飞书群内发一张进度卡片。

**Nag reminder**：连续 N 轮没调 `todo_write` → 自动注入提醒。

**业务特化**：通过 Skill 实现。Learning Skill 教 LLM 用 todo 做学习循环，Work Skill 教 LLM 用 todo 做工作任务。

---

## Skill 系统

Skill 是一个 markdown 文件，放在 `.berry/skills/<name>/SKILL.md`。

LLM 通过 `skill` 工具加载它，然后按内容里的行为准则执行。没有代码编排、没有状态机——纯粹靠 prompt 约束 LLM 行为。

### 写一个新 skill

```bash
mkdir -p .berry/skills/my-skill
cat > .berry/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: "One-line description"
---

# My Skill

Behavioral instructions here...
EOF
```

重启后自动发现并注入 system prompt。

---

## 本地运行

### 前置

- macOS / Linux、Python 3.12+、PostgreSQL 16、[uv](https://github.com/astral-sh/uv)

### 安装 + 启动

```bash
uv sync
cp .env.example .env
# 编辑 .env 填 DATABASE_URL + LLM key + 飞书凭证

uv run alembic upgrade head

# 飞书模式
uv run python -m berry.entrypoints.feishu

# CLI 模式
uv run python -m berry.entrypoints.cli
```

### 测试

```bash
uv run pytest tests/ -v
```

---

## 配置 LLM

编辑 `config/models.yaml`：

```yaml
version: 1
models:
  - id: main
    kind: text
    api: anthropic-messages
    provider: anthropic
    base_url: https://api.anthropic.com
    model_name: claude-sonnet-4-20250514
    api_key: ${ANTHROPIC_API_KEY}
```

---

## License

MIT
