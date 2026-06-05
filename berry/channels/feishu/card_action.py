"""Card button click handler — V1 接入,MVP 不实现。

对齐 openclaw `extensions/feishu/src/card-action.ts`:`card.action.trigger`
事件路由 → 解码 envelope → 合成一条消息事件再次进入主消息 pipeline(不走
另一套分支),让审批 / 重置等按钮逻辑复用 handle_feishu_message。

接入路径(后续):
1. 在 EventDispatcher.builder 上 register_p2_card_action_trigger(handler)
2. handler 解 raw.event.action.value(JSON)→ 决定动作类型
3. 对审批类:调 berry.core.agent.approval.ApprovalChannel 注册的 future
   resolve;对其他动作:合成 FeishuMessageEvent 调 handle_feishu_message
"""
