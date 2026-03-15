"""Session conversation memory — shared across all CRM Agent modules.

Mirrors the n8n 'Simple Memory2' node (memoryBufferWindow keyed by sessionId).

Design
------
All agents share a single in-process _store dict, keyed by session_id.
Sessions from different agents are namespaced automatically because each
agent passes its own session_id format (e.g. ``accounts-<uuid>`` vs
``contacts-<uuid>``).  If you want hard isolation, prefix the session_id
in the agent's router before calling save_turn / get_history.

Thread-safety note
------------------
Safe for single-process async (FastAPI + one Uvicorn worker).
For multi-worker deployments swap _store for a Redis-backed implementation.

Adding a new agent
------------------
No changes needed.  Import and call get_history / save_turn as usual.
"""

import logging
from collections import deque
from typing import List, Dict, Any

from .config import get_settings

logger = logging.getLogger(__name__)

# { session_id: deque([{role, content}, ...]) }
# Each pair of user + assistant messages = one "turn".
# Window cap = memory_window_size * 2 individual messages.
_store: Dict[str, deque] = {}


def _get_deque(session_id: str) -> deque:
    settings = get_settings()
    max_len = max(0, settings.memory_window_size) * 2
    if session_id not in _store:
        _store[session_id] = deque(maxlen=max_len if max_len > 0 else None)
    return _store[session_id]


# ── Public API ────────────────────────────────────────────────────────────────

def get_history(session_id: str) -> List[Dict[str, Any]]:
    """
    Return conversation history for session_id as a list of message dicts:
        [{\"role\": \"user\", \"content\": \"...\"}, {\"role\": \"assistant\", ...}, ...]
    Oldest first; ready to prepend before the current user message.
    Returns [] when memory is disabled (window_size == 0) or session is new.
    """
    settings = get_settings()
    if settings.memory_window_size <= 0:
        return []

    dq = _store.get(session_id)
    if not dq:
        return []

    history = list(dq)
    logger.debug(f"Memory get_history — session={session_id!r}, {len(history)} messages")
    return history


def save_turn(session_id: str, user_message: str, assistant_message: str) -> None:
    """
    Persist one turn (user + assistant) to the rolling window.
    Oldest turns are evicted automatically once maxlen is reached.
    No-op when memory is disabled (window_size == 0).
    """
    settings = get_settings()
    if settings.memory_window_size <= 0:
        return

    dq = _get_deque(session_id)
    dq.append({"role": "user",      "content": user_message})
    dq.append({"role": "assistant", "content": assistant_message})

    logger.debug(
        f"Memory save_turn — session={session_id!r}, "
        f"window now {len(dq)}/{dq.maxlen} messages"
    )


def clear_session(session_id: str) -> None:
    """Remove all history for a session (useful for testing / manual resets)."""
    if session_id in _store:
        del _store[session_id]
        logger.info(f"Memory cleared for session={session_id!r}")


def active_sessions() -> List[str]:
    """Return a list of session IDs that currently have stored history."""
    return list(_store.keys())
