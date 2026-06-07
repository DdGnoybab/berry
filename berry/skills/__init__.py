"""Skills — business capabilities loaded by the agent engine via SkillTool.

Each ``skills/<name>/`` is a self-contained skill package, loaded
on-demand at the LLM's request. Skills are NOT a layer in the
dependency graph (``core/`` doesn't import them); they're treated
like markdown configuration data.

See ADR-0008 for the rationale (replaces the older ``assistants/`` layer).
"""
