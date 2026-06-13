# Berry

> 一个对标 Claude Code 的 AI 编程助手。
> 主要入口是 **Web**(浏览器里用,登录即开聊),同时接入了 **飞书机器人**(手机上跟同一个 agent 继续聊)。

---

## 这是什么

Berry 是一个通用的交互式 AI 助手运行时。

你提需求,它会**读代码、改文件、跑命令、搜网页**,把任务做完;遇到 `rm` / 写文件 / 跑 bash 这类**会改环境的操作**,先弹按钮问你是否同意,你点确认才执行。

**设计哲学**:
- 主循环是通用的,不写死任何业务
- 业务能力靠 markdown 描述(`.berry/skills/<name>/SKILL.md`),LLM 按指引执行
- 加新场景 = 加一个 markdown 文件,不动 runtime 代码

---

## 主要特性

### Agent 引擎
- **手写 Turn Loop(~700 行)** — LLM 决定调工具 → 执行 → 喂回 LLM,直到任务完成。**不用 LangChain / LangGraph**,每个决策都看得见
- **14 个工具** — `read_file` / `write_file` / `edit_file` / `bash` / `grep` / `web_search` / `web_fetch` / `todo_write` / `todo_read` / `memory_read` / `memory_write` / `skill` / `task` / `ask_user_question`
- **多 Provider** — Anthropic Messages / OpenAI Chat Completions 双协议适配,改 YAML 切 DeepSeek / Anthropic / OpenAI 兼容端点
- **LLM 错误恢复(288 行状态机)** — 错误分类(429/5xx/timeout 才重试,认证错不重试) → 指数退避 + jitter(500ms 起跳,封顶 32s) → 服务器 `Retry-After` 头优先 → 单模型到上限切 fallback 链 → 流已开始吐字就不再重试(避免文本拼接出问题)
- **四层上下文压缩管线** — 大工具结果落盘 / 裁旧对话 / 占位旧 tool result / LLM 全量摘要,便宜的先跑;压完后清理孤儿 `tool_use ↔ tool_result` 块
- **审批模型** — 危险工具调用前发审批请求,Web 走前端 modal,飞书走卡片按钮,CLI 走终端;同一套审批语义跨通道复用
- **行为纠偏 reminder** — 正则检测"LLM 把选项写成纯文本而没调按钮工具"、"LLM 让用户点不存在的按钮",下一轮自动注入 `<reminder>` 纠正
- **记忆系统** — 每轮自动提取用户偏好 / 项目事实,以 markdown frontmatter 形式持久化,系统提示注入索引

### Web 前端(主要入口)
- **React 18 + Vite + TypeScript** 单页应用
- **SSE 流式聊天** — `text_delta` / `tool_call_start` / `tool_result` 事件实时渲染
- **按钮交互** — LLM 想问选择题时调 `ask_user_question` 工具,前端实时渲染按钮组;**只有最后一条等回复的消息按钮可点**,历史消息按钮自动失效
- **登录认证** — Cookie session,中间件保护所有 `/v1/*` 端点
- **侧边栏** — 项目 / 会话两级管理

### 飞书 Channel
- **WebSocket 长连** — 免公网回调
- **流式卡片** — 助手回复实时更新到卡片
- **审批卡片** — 危险操作弹按钮,操作人合法性校验
- **Todo 卡片** — todo 状态变化实时渲染进度
- **去重** — 飞书重投的消息不重复处理

### CLI Channel
- **终端 REPL** — 流式渲染 + 终端审批

---

## 快速开始

### 前置

- Python 3.12+、PostgreSQL 16、[uv](https://github.com/astral-sh/uv)
- Node.js 20+(Web 前端)

### 后端

```bash
uv sync
cp .env.example .env
# 编辑 .env 填 DATABASE_URL + LLM key

uv run alembic upgrade head

# 主入口:Web
uv run python -m berry.entrypoints.web         # http://localhost:8000

# 其他入口
uv run python -m berry.entrypoints.feishu      # 飞书(需要飞书凭证)
uv run python -m berry.entrypoints.cli         # CLI
```

### 前端(开发模式)

```bash
cd web
npm install
npm run dev           # http://localhost:5173,代理到后端 8000
```

### 测试

```bash
uv run pytest tests/ -v                         # 8600+ 行测试
uv run ruff check .
uv run mypy berry/
uv run lint-imports                             # 11 条依赖规则 CI 强制
```

---

## Docker 部署

```bash
cp deploy/env.production.example .env.production
# 编辑 .env.production 填真实凭证

docker compose up -d --build
docker compose exec berry alembic upgrade head
```

服务:`berry`(FastAPI)+ `postgres`(PG 16)+ `web`(Nginx 静态托管 Vite build)+ `redis`(可选)

---

## 配置

### LLM 模型

`config/models.yaml` 配模型 catalog,环境变量替换:

```yaml
version: 1
models:
  - id: deepseek-anthropic
    api: anthropic-messages
    provider: deepseek
    base_url: https://api.deepseek.com/anthropic
    model_name: deepseek-chat
    api_key: ${DEEPSEEK_KEY}

aliases:
  main: deepseek-anthropic              # 默认
  fallback: anthropic-claude            # 主模型挂了切这个
```

### 环境变量

详见 [`.env.example`](.env.example),主要:
- `DATABASE_URL` — PostgreSQL 连接串
- `DEEPSEEK_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — LLM 凭证
- `TAVILY_KEY` — 网页搜索
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` — 飞书凭证(用 Web 不需要)

---

## 架构

**Modular Monolith + Package by Feature**:5 大模块,11 条依赖规则由 `import-linter` 在 CI 强制(违反则构建失败)。

```
              entrypoints/        ← 进程组装层
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   channels/  gateway/   skills/   ← 通道 / 控制平面 / 业务能力
        \        /         │
         \      /          │
          ─────────► core/         ← agent 引擎 / LLM 网关 / 工具 / DB
                       │
                       ▼
                    domain/        ← 纯模型 / 异常
```

- `core/` — 通用 AI 引擎(turn loop / LLM 网关 / 工具 / DB / 沙箱占位)
- `channels/` — 通道层(`web/` `feishu/` `cli/`),平级互不 import
- `gateway/` — HTTP 路由 / Method Registry / Inbox 占位
- `skills/` — 业务能力(目前一个 learning)
- `domain/` — 跨模块纯模型 / 事件 / 异常

详见:
- [`docs/berry-project-structure.md`](docs/berry-project-structure.md) — 完整目录树 + 决策树
- [`docs/adrs/`](docs/adrs/) — 架构决策记录(10 篇)
- [`CLAUDE.md`](CLAUDE.md) — 架构约束 + 代码规范

---

## 当前状态

### ✅ 已完成
- ConversationRuntime(turn loop / 流式 / 工具调度 / 审批)
- LLM 错误恢复(重试 + 退避 + Retry-After + fallback)
- 四层上下文压缩管线
- 14 个工具
- Web channel(登录 / SSE 流式 / 按钮交互 / 项目-会话两级管理)
- 飞书 channel(WebSocket 长连 / 流式卡片 / 审批卡片 / 去重)
- CLI channel(REPL / 流式 / 终端审批)
- Memory 系统(自动提取 + 持久化 + 系统提示注入)
- Hook 系统(PreToolUse,ALLOW/DENY/DEFER)
- 行为纠偏 reminder(numbered_list / phantom_buttons)

### 🔲 待实现
- Sandbox 隔离(Protocol 占位,未接 Docker / e2b)
- 多 Skill(目前只有 learning,要加 work / style 等)
- RAG 个人记忆检索
- Langfuse / Prometheus 可观测性
- Redis 分布式锁 / 限流

---

## License

MIT
