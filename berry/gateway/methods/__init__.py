"""Method registry + core method handlers.

Startup calls register_core(registry); domains then register their own.
"""

from berry.gateway.methods.registry import CallContext, MethodRegistry


def register_core(registry: MethodRegistry) -> None:
    """Register all core method handlers to registry."""
    from berry.gateway.methods import (
        approval,
        learning_plan,
        llm_call,
        project,
        session,
        session_resume,
        system,
        task,
        turn,
        upload,
    )

    system.register(registry)
    project.register(registry)
    session.register(registry)
    turn.register(registry)
    approval.register(registry)
    task.register(registry)
    upload.register(registry)
    llm_call.register(registry)
    learning_plan.register(registry)
    session_resume.register(registry)


__all__ = ["CallContext", "MethodRegistry", "register_core"]
