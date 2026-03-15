"""LangGraph agent module for the Accounts domain.

Mirrors the n8n Account API v2 workflow topology:
  pre_router ─┬─[direct_db]──→ db ──→ format → END
              └─[ai_agent]──→ ai_agent → parse ─┬─[call_db]──→ db → format → END
                                                 └─[skip_db]──→ format → END

All shared utilities (AgentState, LLM factory, JSON parser, graph builder)
come from app.core.graph_utils.  Domain-specific concerns (prompt, pre_router,
sql_builder, formatter) stay in this package.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from app.core.graph_utils import (
    AgentState,
    _get_llm,
    _call_ollama_direct,
    parse_ai_json,
    build_standard_graph,
)
from app.core.memory import get_history, save_turn
from app.core.config import get_settings
from app.core.database import execute_sp

from .prompt import ACCOUNT_AGENT_SYSTEM_PROMPT
from .pre_router import route_request
from .sql_builder import build_accounts_query
from .formatter import format_response

logger = logging.getLogger(__name__)


# ============================================================================
# NODES
# ============================================================================

def pre_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-Router — mirrors n8n Pre Router Code node v3.0."""
    logger.info("=== Accounts Pre-Router Node (v3.0) ===")
    user_input = state.get("user_input", "")
    chat_input = state.get("chat_input", {})
    logger.info(f"Session: {state.get('session_id')!r}  Message: {user_input[:100]}")

    result = route_request(user_input, chat_input)

    if result["router_action"]:
        params = result["params"]
        logger.info(f"Accounts pre-router ROUTED → mode={params.get('mode')}")
        return {**state, "router_action": True, "parsed_json": params, "should_call_api": True}

    logger.info(f"Accounts pre-router PASSTHRU → {result['current_message'][:80]}")
    return {**state, "router_action": False, "user_input": result["current_message"]}


def ai_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """AI Agent node — invokes LLM with the accounts system prompt."""
    logger.info("=== Accounts AI Agent Node ===")
    session_id = state.get("session_id", "default-session")
    user_input = state.get("user_input", "")

    settings   = get_settings()
    history    = get_history(session_id)
    messages   = history + [{"role": "user", "content": user_input}]

    try:
        if settings.llm_provider == "openai":
            llm = _get_llm()
            full_messages = [{"role": "system", "content": ACCOUNT_AGENT_SYSTEM_PROMPT}] + messages
            response  = llm.invoke(full_messages)
            ai_output = response.content if hasattr(response, "content") else str(response)
        else:
            ai_output = _call_ollama_direct(ACCOUNT_AGENT_SYSTEM_PROMPT, messages)

        clean = re.sub(r"<think>[\s\S]*?</think>", "[think]", ai_output).strip()
        logger.info(f"Accounts AI output ({len(ai_output)} chars): {clean[:200]}")
        return {**state, "ai_output": ai_output}

    except Exception as e:
        logger.error(f"Accounts AI Agent error: {e}", exc_info=True)
        return {**state, "ai_output": f"Error: {str(e)}"}


def parse_output_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Parse AI Output — extract JSON from the LLM's response."""
    logger.info("=== Accounts Parse Output Node ===")
    parsed = parse_ai_json(state.get("ai_output") or "")
    if parsed:
        return {**state, "parsed_json": parsed, "should_call_api": True}
    return {**state, "parsed_json": None, "should_call_api": False}


def db_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Database node — builds and executes sp_accounts()."""
    logger.info("=== Accounts Database Node ===")
    try:
        parsed_json = state.get("parsed_json") or {}
        if not parsed_json:
            return {**state, "db_rows": []}

        query, _ = build_accounts_query(parsed_json)
        logger.info(f"Built sp_accounts query for mode: {parsed_json.get('mode')}")

        db_rows = execute_sp(query)
        logger.info(f"sp_accounts returned {len(db_rows)} rows")
        return {**state, "db_rows": db_rows}

    except Exception as e:
        logger.error(f"Accounts database error: {e}", exc_info=True)
        return {**state, "db_rows": [{"result": {
            "metadata": {"status": "error", "code": -500, "message": str(e)}
        }}]}


def formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Formatter node — formats output and persists turn to memory."""
    logger.info("=== Accounts Formatter Node ===")
    try:
        if state.get("should_call_api"):
            db_rows     = state.get("db_rows") or []
            parsed_json = state.get("parsed_json") or {}
            final_output = format_response(db_rows, parsed_json)
        else:
            final_output = state.get("ai_output") or "No response generated"

        session_id = state.get("session_id", "default-session")
        user_input = state.get("user_input", "")
        if user_input and final_output:
            save_turn(session_id, user_input, final_output)

        return {**state, "final_output": final_output}

    except Exception as e:
        logger.error(f"Accounts formatter error: {e}", exc_info=True)
        return {**state, "final_output": f"Error formatting response: {str(e)}"}


# ============================================================================
# GRAPH SINGLETON
# ============================================================================

_graph_app = None


def get_graph():
    global _graph_app
    if _graph_app is None:
        _graph_app = build_standard_graph(
            pre_router_node=pre_router_node,
            ai_agent_node=ai_agent_node,
            parse_output_node=parse_output_node,
            db_node=db_node,
            formatter_node=formatter_node,
            graph_label="Accounts Agent",
        )
    return _graph_app
