"""Process-level singletons used by the feishu channel.

对齐 openclaw `extensions/feishu/src/monitor.state.ts`。把这些状态放进单例
dict 而不是某个 class instance,纯粹是为了:
1. 多 account 时按 account_id 索引能并存
2. 不传依赖也能在 `bot.handle_feishu_message` 拿到 HTTP client
3. 跟 openclaw 行为一致(它也是模块级单例)

MVP 只 1 个 account,但表保持 dict 形态,后续多 account 不动结构。
"""

from __future__ import annotations

import lark_oapi as lark

from berry.channels.feishu.types import ResolvedFeishuAccount

# account_id -> lark.Client(HTTP,用于 im.message.create 等)
_http_clients: dict[str, lark.Client] = {}

# account_id -> bot 自己的 open_id(parse 出来后写)
_bot_open_ids: dict[str, str] = {}

# account_id -> ResolvedFeishuAccount(启动时填充)
_resolved_accounts: dict[str, ResolvedFeishuAccount] = {}


def set_http_client(account_id: str, client: lark.Client) -> None:
    _http_clients[account_id] = client


def get_http_client(account_id: str) -> lark.Client:
    return _http_clients[account_id]


def set_bot_open_id(account_id: str, open_id: str) -> None:
    _bot_open_ids[account_id] = open_id


def get_bot_open_id(account_id: str) -> str | None:
    return _bot_open_ids.get(account_id)


def set_resolved_account(account: ResolvedFeishuAccount) -> None:
    _resolved_accounts[account.account.account_id] = account


def get_resolved_account(account_id: str) -> ResolvedFeishuAccount | None:
    return _resolved_accounts.get(account_id)


def clear() -> None:
    """测试 / shutdown 用。"""
    _http_clients.clear()
    _bot_open_ids.clear()
    _resolved_accounts.clear()
