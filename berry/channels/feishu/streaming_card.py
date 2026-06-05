"""Streaming card — V1 接入,MVP 不实现。

对齐 openclaw `extensions/feishu/src/streaming-card.ts`:CardKit v2 streaming
card,先 POST 建卡 → PATCH 增量更新 → close 关 streaming_mode,160ms 节流 +
自然边界判断。

为什么 MVP 不做:
- 飞书 CardKit v2 需要单独的卡片创建 / 更新 API,流量 throttle / 自然边界
  判断逻辑较多,设计文档已记。
- MVP 单条 markdown 卡片就能让用户拿到完整回复,够用。

接入路径(后续):
1. 实现 FeishuStreamingSession(start / update / close)
2. 在 reply_dispatcher.py 里把 ConversationRuntime 的 AgentEvent stream 喂给它
3. bot.handle_feishu_message 不再 drain final_text,改成实时流式
"""
