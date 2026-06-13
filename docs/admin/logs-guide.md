# 日志使用指南

> 这是 `/admin/logs` 面板的使用文档。
> 你打开它,通常是因为有用户反馈了奇怪的问题,需要复盘到底发生了什么。

## 1 分钟入门

```
┌──────────────────────────────────────────────────────────┐
│ Date [今天]  From [00:00]  To [23:59]                    │
│ [ERROR][WARN][INFO][DEBUG]   🔍 search…                  │
│ [Follow][Clear][Download]    142 shown · 1893 matched   │
├──────────────────────────────────────────────────────────┤
│ 14:23:01.124  INFO   user_login          user_id="..."   │
│ 14:23:03.422  INFO   llm_wire_request    wire_id="..."   │
│ 14:23:08.901  INFO   llm_wire_response   wire_id="..."   │
│ 14:23:19.220  ERROR  feishu_send_card_failed  ...        │
└──────────────────────────────────────────────────────────┘
```

- **Follow** 默认开,新日志自动滚到底
- **改日期/选 level/输关键字** → 离开 follow 模式,变成查询历史
- **点任意一行** → 行下方展开看完整 JSON
- 行末有 `▶ payload` 标记 → 那一行带了重字段(LLM 请求/响应等),点行才看得到

## 2 分钟看懂一条日志

每行长这样:

```
14:23:01.124  INFO   llm_wire_request   wire_id="a1b2..." api="anthropic_messages" model_logical="main"  ▶ payload
└─时间─┘     └level┘ └─── event ───┘    └─────── inline kv (一眼能扫的元信息) ────────┘            └ 重字段标记 ┘
```

- **event** 是这条日志的"类型",snake_case,代码里硬编码,**最重要的字段**
- **inline kv** 是元信息,`event` 后面跟的几个,grep 友好
- **重字段** 比如 `payload`、`exception`,行内不展开,**点行才看**

## 排查思路

不要盲目 grep,先想清楚要找的"主体"是什么:

| 你要找的 | 用什么字段过滤 |
|---|---|
| 某个用户的全部行为 | 搜 `user_id="xxx"` |
| 某次 LLM 调用的请求 → 响应配对 | 搜某条的 `wire_id="xxx"` 出两条 |
| 某次会话发生了什么 | 搜 `session_id="xxx"` |
| 某个时间点附近全部 ERROR | 选时间范围 + ERROR level |
| 某用户为什么进度对不上 | 搜 `user_id` + `learning_*` 或 `memory_written` |

---

## Event 名称完整表(按类别)

事件名是 `snake_case`,**第一个 `_` 之前的部分通常是分类**(`llm_*`、`feishu_*`、`memory_*` 等)。
下表按类别列出常见 event,每条一句话讲它什么时候出现 / 关键 inline 字段。

### LLM 调用(切面日志,wire 层)

`berry/core/llm/adapters/*.py` 在调用厂商 SDK 前后打。**最常用的诊断字段**。

| event | 何时出现 | 关键字段 |
|---|---|---|
| `llm_wire_request` | 即将调 SDK,把完整 body 送出去前 | `wire_id` `api` `mode`(invoke/stream) `model_logical` `model_provider` `payload` |
| `llm_wire_response` | invoke 收到 SDK 返回 | `wire_id` `duration_ms` `payload`(SDK Response dump) |
| `llm_wire_stream_done` | stream 自然结束 | `wire_id` `event_count`(累计 chunk 数) `duration_ms` `payload`(完整事件序列) |
| `llm_wire_failed` | SDK 抛异常 | `wire_id` `error_type` `error` `duration_ms` |

**用法**:
- 想看"berry 真发了什么 JSON 给 Anthropic" → 找 `llm_wire_request` 点开 payload
- 想看"模型真返回了什么" → 找同 wire_id 的 `llm_wire_response` 或 `llm_wire_stream_done`
- request / response 一对一靠 `wire_id` 配对,搜某个 wire_id 一定出两条

### 学习编排(learning 业务层)

`berry/skills/learning/` 在创建 / 推进学习项目时打。

| event | 何时出现 | 关键字段 |
|---|---|---|
| `learning_create_workspace_init` | 用户新建 topic,workspace 目录刚铺好 | `project_id` `workspace` |
| `learning_create_files_written` | ROADMAP / progress.json 等模板文件落盘 | `project_id` `files` |
| `learning_create_project_failed_rolling_back` | 新建过程报错,触发回滚 | `project_id` `error_type` `error` |
| `learning_create_session` | 新建 session 成功 | `project_id` `session_id` |
| `learning_skill_synced` | 启动时 skill 模板从代码同步到 workspace | `path` |
| `learning_persona_read_failed` | LEARNER.md 读失败 | `path` `error` |
| `progress_json_read_failed` | `.berry/progress.json` 损坏 / 不存在 | `path` `error_type` |
| `learner_md_template_written` | LEARNER.md 模板首次写入 | `path` |

**用法**:
- 用户说"新建 topic 失败" → 找 `learning_create_project_failed_rolling_back`,看 error
- 用户说"进度条不对" → 找 `progress_json_read_failed`,可能 json 损坏

### 会话与回放(resume / session)

`berry/gateway/methods/session*.py`。

| event | 何时出现 |
|---|---|
| `resume_create_no_runner` | 试图 resume 但 runtime 没装配 |
| `resume_create_session_load_failed` | 加载历史 session 出错 |
| `resume_create_turn_failed` | 起 priming turn 时模型挂了 |
| `resume_progress_read_failed` | resume 时读 progress.json 出错 |
| `create_project_priming_turn_failed` | 新项目首轮欢迎被打断 |
| `create_project_session_load_failed` | 创建后立刻加载新 session 出错 |

**用法**:用户说"点新会话没反应" → 找 `resume_create_*`、`create_project_*`,大概率 ERROR 行。

### 历史压缩(compaction)

`berry/core/agent/compaction*.py`。会话历史超长时分级压缩。

| event | 何时出现 |
|---|---|
| `compaction_l1_snip` | L1:把工具长 output 截断成预览 |
| `compaction_l2_micro` | L2:每条 message 内做 micro 压缩 |
| `compaction_l3_budget` | L3:整个 turn 超 budget,从最旧的开始丢/压 |
| `compaction_l3_persist_failed` | L3 持久化中间结果失败 |
| `compaction_l4_history` | L4:跨 session 历史归档 |
| `compaction_reactive` | 触发了反应式压缩(临时挽救一次超长) |
| `compaction_transcript_saved` | 当前 turn 的完整 transcript 落盘成功 |
| `compaction_transcript_failed` | 上面那条的 ERROR 版 |

**用法**:用户说"对话越来越慢 / 上下文丢失" → 看 `compaction_*` 频率,L3/L4 频繁说明对话太长该开新 session。

### 工具与提示(tools / hooks)

| event | 何时出现 |
|---|---|
| `hook_decided` | 工具调用被 pre-tool hook 放行 / 拒绝 / 改写 |
| `hook_raised` | hook 自己抛了异常 |
| `tool_use_input_parse_error` | 模型给的 tool args JSON 烂了 |
| `edit_file_in_workspace` | edit 工具改了文件(注意:这是输出 `event_name`,不固定) |
| `persistence_sanitize_dropped` | 写历史时丢弃了无效 content block |

**用法**:用户说"工具说没权限 / 改不动文件" → 找 `hook_decided`,看 `decision` 字段。

### 内存系统(memory)

`berry/core/tools/memory/`。LLM 提取的"用户偏好 / 项目事实"。

| event | 何时出现 |
|---|---|
| `memory_extracted` | 一轮 turn 后从对话里提取出几条记忆 |
| `memory_written` | 单条记忆落盘到 `data/memory/<user_id>/*.md` |
| `memory_consolidated` | 同主题旧记忆被合并/重写 |
| `memory_consolidate_no_changes` | 巩固跑完没改动(常态,不是问题) |
| `memory_load_failed` | 加载 memory 索引出错 |
| `memory_extract_failed` | 抽取 LLM 调用失败 |
| `memory_side_query_failed` | turn 中并发查 memory 失败 |
| `memory_deleted` | 用户主动删了某条记忆 |

**用法**:用户说"模型不记得我之前说的偏好了" → 搜 `memory_written` 看是不是真有那条;再看 `memory_extract_failed` 看抽取是不是挂了。

### 飞书 channel(`feishu_*`)

发卡片 / 收事件 / 卡片回调,数量最多。**关键几个**:

| event | 何时出现 |
|---|---|
| `feishu_ws_starting` / `feishu_ws_returned` / `feishu_ws_terminated` | WebSocket 长连生命周期 |
| `feishu_send_text_api_error` / `feishu_send_card_failed` | 发消息 / 发卡片 API 失败 |
| `feishu_approval_card_sent` / `feishu_approval_resolved` | 审批卡片下发 / 用户点了之后被处理 |
| `feishu_card_action_*` | 用户点按钮的 envelope 解析全程 |
| `feishu_dedup_hit` | 同一事件重复进来(SDK 重发),被去重 |
| `feishu_turn_failed` | 飞书 turn runtime 挂掉 |

**用法**:用户在飞书说"机器人没回我" → 先确认 `feishu_ws_starting`(连上没),再搜该 chat_id 看有没有 `feishu_send_*` 错误。

### 认证(auth)

| event | 何时出现 |
|---|---|
| `user_login` | 用户登录成功 |
| `health_check_postgres_failed` | DB 健康检查失败 |

(失败的登录不打日志 —— 防字典攻击日志注入。401 直接返回。)

### 启停(lifecycle)

| event | 何时出现 |
|---|---|
| `berry_starting` | 进程启动 |
| `berry_stopping` | 进程优雅停 |
| `web_http_rpc_configured` | web 入口 RPC 注册完成 |
| `web_default_workspace_resolved` | 默认 workspace 路径就位 |

### 日志系统自身

| event | 何时出现 |
|---|---|
| `log_read_failed` | `/admin/logs` 读某文件失败(被锁?权限?)|
| `log_stream_backfill_failed` | `/stream` 端 SSE 回填最近 200 行时挂了 |

(看到这两个 ERROR 时小心 —— 日志系统自己病了,信任度下降。)

---

## 常见排查 cookbook

### "用户说今天某次回复中模型答错了,想看当时发了什么"

1. 选日期 = 今天
2. 关键字搜用户原话里的一段(比如 `redis 持久化`)
3. 命中 `llm_wire_request`,点开 payload 看 messages
4. 用同行的 `wire_id` 再搜一次,拿到 `llm_wire_response` / `llm_wire_stream_done`
5. 点开 payload 看模型真返回的 content

### "用户说飞书发了消息没收到回复"

1. 选时间窗(用户大概什么时候发的)
2. 关键字搜 `feishu_`
3. 先看有没有 `feishu_ws_starting` / `feishu_ws_terminated` —— 连接挂了就到这一步
4. 没问题就看 `feishu_turn_failed` —— 模型这边挂了
5. 都没看到 → 看 `feishu_dedup_hit`,可能整个事件被去重吃了

### "DB 看着对,前端进度条不动"

1. 搜 `progress_json_read_failed` 看 progress.json 是不是损坏
2. 搜 `learning_create_files_written` 看创建项目时模板有没有写下去
3. 搜 `memory_written` 名字含 skip → 用户跳过的 memory 落了没

### "用户说审批卡片点了没用"

1. 搜 `feishu_approval` 看完整链:
   - `feishu_approval_card_sent` 卡片发出去了
   - `feishu_card_action_*` 用户点击事件解析
   - `feishu_approval_resolved` 处理成功
2. 缺哪一步,问题就在哪一步

### "想知道线上 LLM 调用大概多慢"

1. level = INFO,关键字搜 `llm_wire_response` 或 `llm_wire_stream_done`
2. 每行 inline 字段都有 `duration_ms`
3. 想看分布 → Download 当天 .log,本地 jq 处理

---

## 高级技巧

### Download + jq

面板看不下海量数据时,Download 当天 .log,本地用 jq:

```bash
# 当天所有 LLM 调用的耗时
zcat berry.log.2026-06-13.gz | grep llm_wire_response \
  | jq -c '{ts:.timestamp, model:.model_logical, ms:.duration_ms}'

# 错误里 error_type 分布
zcat berry.log.*.gz | jq 'select(.level=="error") | .error_type' | sort | uniq -c
```

### Live tail 限制

只有"今天 + 全天 + 无关键字过滤 + 无 level 过滤"时 Follow 才可用 ——
否则查询语义就模糊了(让查询历史和 live tail 行为分明)。

### 日志保留期

默认 **3 天**,UTC 0 点切片,旧文件 gzip,超期自动删。
想拉更长历史:改 `LOG_RETENTION_DAYS` 重新部署。

### 想加新 event

按 `docs/logging-conventions.md` 的命名约定写,加完同步更新本文件 event 表。
