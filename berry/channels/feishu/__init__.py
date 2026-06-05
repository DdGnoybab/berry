"""Feishu channel — DM 单聊 MVP。

文件切分对齐 openclaw `extensions/feishu/src/`(参考 docs/2026-06-04-feishu-channel-design.md)。
对外 entry 是 `monitor_feishu_provider`(实现见 `monitor.py`,由
`berry.entrypoints.feishu` 调用)。

故意不在这里 re-export — 调用方用全路径 import,避免循环依赖,且与 openclaw
风格一致(extensions/feishu 也是按文件直接 import,不绕 barrel)。
"""
