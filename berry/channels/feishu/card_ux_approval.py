"""Approval card UI — V1 接入,MVP 不实现。

对齐 openclaw `extensions/feishu/src/card-ux-approval.ts`:危险工具调用前
弹出 Confirm/Cancel 按钮卡片;berry 这边目标接到 `core.agent.approval.
ApprovalChannel` Protocol。

接入路径(后续):
1. 实现 build_approval_card(tool_name, args) → Feishu card JSON
2. 实现 FeishuApprovalChannel:ApprovalChannel.ask 内发卡片 + 创建 future,
   等 card_action 回调 resolve
3. entrypoints/feishu.py 里把 FeishuApprovalChannel 注入 ConversationRuntime
"""
