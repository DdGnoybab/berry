# Berry

> 飞书原生个人工作台 / 编码 Agent 后端。
> 当前版本:**v0.0.1**(production-grade skeleton)

---

## 这是什么

Berry 是一个跑在云上的飞书原生 LLM agent 后端。
你在飞书里下指令,Berry 在云端帮你过滤信息流、整理想法、跑代码 demo。

## 当前状态(v0.0.1)

✅ **底层钢梁就位**:
- FastAPI + Postgres + alembic 项目骨架
- 3 张业务表(users / sessions / messages)
- LLM Gateway:**按协议抽象** + 自定义中立类型
- 已支持 Anthropic Messages / OpenAI Chat Completions 两种协议
- 配置驱动多模型(yaml + `${VAR}` env 替换 + 防明文 key)
- 支持流式响应 + 工具调用(tool_use)来回

🔘 **上层业务待实现**:
- 飞书 channel 接入(lark-oapi WebSocket)
- LangGraph 编排(StateGraph + checkpointer + interrupt)
- Agent 节点 / 工具(Read/Write/Edit/Bash)
- Sandbox 隔离

## 技术栈

| 层 | 选型 |
|---|---|
| 包管理 | uv |
| Python | 3.12+ |
| Web | FastAPI + uvicorn |
| 数据库 | PostgreSQL 16 + asyncpg / psycopg |
| ORM | SQLModel + alembic |
| LLM | anthropic + openai 官方 SDK 直连 |
| 日志 | structlog |
| 类型 / 风格 | mypy strict + ruff |

## 架构

**Modular Monolith + Package by Feature**:单进程多模块,按业务能力切。
依赖方向用 import-linter 强制。

```
berry/
├── llm/                  ★ LLM Gateway(已就绪)
│   ├── gateway.py        对外唯一入口
│   ├── registry.py       配置驱动的模型 catalog
│   ├── types.py          中立类型(LlmRequest/Response/StreamEvent)
│   └── adapters/
│       ├── anthropic_messages.py
│       └── openai_completions.py
├── db/                   ★ 数据持久化(已就绪)
├── agent/                🔘 待实现(LangGraph)
├── feishu/               🔘 待实现(channel)
├── tools/                🔘 待实现(Tool 实现)
├── sandbox/              🔘 待实现(per-workspace 隔离)
└── ...
```

## 本地运行

### 前置

- macOS / Linux
- Python 3.12+
- PostgreSQL 16
- [uv](https://github.com/astral-sh/uv)

### 安装

```bash
# 1. 装依赖
uv sync

# 2. 准备 PG(macOS):
brew install postgresql@16
brew services start postgresql@16
psql postgres -c "CREATE DATABASE berry;"

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填真实的 DATABASE_URL 和 LLM api key
```

### 跑迁移

```bash
uv run alembic upgrade head
```

### 起服务

```bash
uv run berry
# 然后 curl http://127.0.0.1:8000/health
```

### LLM Gateway 联调

```bash
# 非流式
uv run python scripts/llm_smoke.py --prompt "用一句话介绍 Python"

# 流式
uv run python scripts/llm_smoke.py --stream --prompt "你好"

# 工具调用来回
uv run python scripts/llm_smoke.py --model main --tools
```

## 配置 LLM

编辑 `config/models.yaml`:

```yaml
version: 1
models:
  - id: deepseek-chat              # 业务代码用这个 logical id
    kind: text
    api: openai-completions        # 协议
    provider: deepseek
    base_url: https://api.deepseek.com/v1
    model_name: deepseek-chat
    api_key: ${DEEPSEEK_KEY}       # 必须 ${VAR},明文报错
aliases:
  classify: deepseek-chat
```

`.env`:
```
DEEPSEEK_KEY=sk-xxx
```

## License

MIT
