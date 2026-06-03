# Berry

> 通用 AI 助手 runtime + skill 驱动业务场景。
> 灵感来源：Claude Code / Claw Code——做一个通用 agent runtime，通过 skill（markdown prompt）解决具体领域问题。

---

## 这是什么

Berry 是一个通用的交互式 AI 助手 runtime。核心设计：

```
通用 runtime（turn loop + 工具分发 + 审批）
  + Skill 工具（markdown → context 注入）
  + System prompt（身份 + 行为边界）
  = 一个可以做任何事的 agent
```

**设计哲学**：
- Runtime 是通用的——不包含任何业务逻辑
- Skill 是 markdown 文件——描述行为准则，LLM 按指引执行
- 新增场景 = 新增一个 `.berry/skills/<name>/SKILL.md`，不碰 runtime 代码

---

## 当前状态

| 模块 | 状态 |
|------|------|
| Turn loop（ConversationRuntime） | ✅ |
| LLM Gateway（Anthropic / OpenAI / DeepSeek） | ✅ |
| Stream Accumulator | ✅ |
| Tool Protocol + Registry | ✅ |
| Approval model（Policy + Channel） | ✅ |
| System Prompt Builder + skill 发现 | ✅ |
| Skill 工具 | ✅ |
| File tools（read / write / edit） | ✅ |
| Web tools（search / fetch） | ✅ |
| CLI entrypoint + slash commands | ✅ |
| Session persistence（文件系统） | ✅ |
| DB（PostgreSQL + alembic） | ✅ |

---

## 架构

```
berry/
├── core/                     通用 AI 能力（runtime 层）
│   ├── agent/                Turn loop / prompt / session / approval
│   ├── llm/                  Gateway + adapters（Anthropic / OpenAI）
│   ├── tools/                Tool 实现
│   │   ├── core/skill.py     Skill 工具
│   │   ├── files/            read / write / edit
│   │   └── web/              search / fetch
│   ├── db/                   PostgreSQL + repos
│   └── project/              Workspace 管理
├── channels/cli/             CLI REPL
├── entrypoints/cli.py        组装 + 启动
├── gateway/                  Method registry
└── .berry/skills/            Skill 定义（markdown）
```

**依赖方向**：`entrypoints → channels/gateway → core`。Core 不知道有什么 channel 或什么 skill。

---

## Skill 系统

Skill 是一个 markdown 文件，放在 `.berry/skills/<name>/SKILL.md`。

LLM 通过 `skill` 工具加载它，然后按内容里的行为准则执行。没有代码编排、没有状态机——纯粹靠 prompt 约束 LLM 行为。

### 内置 skill

| Skill | 触发 | 用途 |
|-------|------|------|
| learning | `/learn` 或用户表达学习意图 | 面试导向技术学习 |

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
# 编辑 .env 填 DATABASE_URL + ANTHROPIC_API_KEY

uv run alembic upgrade head
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
