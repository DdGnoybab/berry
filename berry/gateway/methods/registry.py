"""Backwards-compatible re-export shim.

The dispatcher infrastructure (``CallContext`` / ``MethodRegistry``)
moved to ``berry.core.agent.method_registry`` in ADR-0009. This module
re-exports those names so existing handler files don't churn.

New code should import from ``berry.core.agent.method_registry`` directly.
"""

from berry.core.agent.method_registry import (
    CallContext,
    MethodRegistry,
    StreamHandler,
    SyncHandler,
)

__all__ = ["CallContext", "MethodRegistry", "StreamHandler", "SyncHandler"]
