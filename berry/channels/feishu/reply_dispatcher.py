"""Streaming reply dispatcher — V1 接入,MVP 不实现。

对齐 openclaw `extensions/feishu/src/reply-dispatcher.ts`:把 LLM 的
AgentEvent stream 包装成「typing → 增量 update card → finalize」的生命周期。

MVP 的非流式实现直接在 bot.handle_feishu_message 里 drain final_text 后
调 send_card_markdown 一次,不需要 dispatcher。本文件存在只是为了文件结构
对齐 openclaw,后续接 streaming card 时把所有 dispatcher 逻辑放这里。
"""
