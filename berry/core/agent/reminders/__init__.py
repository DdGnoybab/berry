"""Per-turn reminders that the runtime injects when LLM behaviour drifts.

Each reminder module exposes:
  - a detector function ``detect(...) -> Reminder | None``
  - a ``REMINDER_TEMPLATE`` string used by the runtime when injecting

Reminders are inserted into the next turn's message stream as a
``<system-reminder>...</system-reminder>`` user-role message — the
LLM treats it as system context, not a user turn.
"""
