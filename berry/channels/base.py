"""Channel Protocol — what every outbound user-facing channel must satisfy.

A Channel:
  - subscribes to ``EventBus`` for one or more sessions
  - translates ``BerryEvent``s into its own user-facing rendering
    (web SSE, Feishu cards, CLI stdout, etc.)
  - optionally drives the inbound flow (Feishu monitors WS messages,
    web routes accept POST requests, CLI reads stdin)

This Protocol is intentionally minimal — most channel logic is
channel-specific and lives in ``berry/channels/<name>/``. The Protocol
exists to satisfy ADR-0001's "channels are Port+Adapter" claim and
make a future ``ChannelRegistry`` (V1+) cheap to add.

Currently no code consumes this Protocol — channels register
themselves via entrypoints. Kept as documentation of the contract
new channels should follow.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    """A user-facing message channel (web / feishu / cli / telegram / ...).

    Implementations:
      - ``channels/web/``     — HTTP + SSE
      - ``channels/feishu/``  — lark-oapi WebSocket
      - ``channels/cli/``     — stdin/stdout

    Implementation note: actual subscription wiring happens in
    ``entrypoints/<name>.py`` rather than via a uniform ``start()``
    signature, because each channel needs different bootstrap inputs
    (lark client, FastAPI app, etc.). Once cross-cutting infrastructure
    stabilises (V1+) this Protocol may grow a ``start()`` method.
    """

    name: str
    """Human-readable channel name (``"web"``, ``"feishu"``, ``"cli"``)."""
