"""learning.* method registration.

Stage 2 minimal: no learning-specific methods registered yet (Stage 2.5
adds progress / material etc.). register() is a no-op placeholder so the
entrypoint registration call stays uniform.
"""

from berry.gateway.methods.registry import MethodRegistry


def register(registry: MethodRegistry) -> None:
    """Register learning.* methods.

    Stage 2: no-op. Stage 2.5: adds material / progress / evaluation etc.
    """
    return
