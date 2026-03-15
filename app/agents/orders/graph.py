"""LangGraph agent module for the Orders domain.

Orders has a richer state than the base agents — it carries:
  body             : the full reconstructed request body (for batchData routing)
  current_message  : preprocessed message (may differ from user_input)
  raw_message      : original unmodified message (used by sql_builder enrichment)
  params           : alias for parsed_json set by pre_router direct path
  format_result    : structured dict returned by format_response (orders formatter
                     returns a dict, not a string, so it can pass side-channel data
                     like order_id, order_number, entity, reportMode back to the
                     HTTP layer)

The graph topology is identical to the standard 5-node DAG; we use
build_graph_with_schema() so the StateGraph is typed against OrderAgentState.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, TypedDict

from app.core.graph_utils import (
    _get_llm,
    _call_ollama_direct,
    parse_ai_json,
    build_graph_with_schema,
)
from app.core.memory import get_history, save_turn
from app.core.config import get_settings
from app.core.database import execute_sp

from .prompt import SYSTEM_PROMPT
from .pre_router import route_request
from .sql_builder import build_orders_query
from .formatter import format_response

logger = logging.getLogger(__name__)


# ============================================================================
# EXTENDED STATE
# Orders carries extra fields beyond the standard AgentState.
# ============================================================================

class OrderAgentState(TypedDict):
    session_id:       str
    body:             dict           # full reconstructed request body
    chat_input:       dict
    user_input:       str
    current_message:  str            # preprocessed message (may equal user_input)
    raw_message:      str            # original unmodified message
    router_action:    bool
    params:           Optional[Dict[str, Any]]   # alias for parsed_json (direct path)
    ai_output:        Optional[str]
    parsed_json:      Optional[Dict[str, Any]]
    should_call_api:  bool
    db_rows:          Optional[List]
    format_result:    Optional[Dict[str, Any]]   # structured dict from formatter
    final_output:     Optional[str]


# ============================================================================
# NODES
# ============================================================================

def pre_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-Router — mirrors n8n Pre Router Code node v4.1."""
    logger.info("=== Orders Pre-Router Node (v4.1) ===")
    body       = state.get("body", {})
    chat_input = state.get("chat_input", {})
    session_id = state.get("session_id", "")

    result = route_request(body, chat_input, session_id)

    if result["router_action"]:
        params = result["params"]
        logger.info(f"Orders pre-router ROUTED → mode={params.get('mode')} action={params.get('action', '')}")
        return {
            **state,
            "router_action":   True,
            "params":          params,
            "parsed_json":     params,
            "should_call_api": True,
        }

    logger.info("Orders pre-router PASSTHRU → AI Agent")
    return {**state, "router_action": False}


def ai_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """AI Agent node — invokes LLM with the orders system prompt."""
    logger.info("=== Orders AI Agent Node ===")
    session_id = state.get("session_id", "default-session")
    # Orders uses current_message (may be enriched) as the LLM input
    current_message = state.get("current_message") or state.get("user_input", "")
    logger.info(f"Session: {session_id!r}  Input: {current_message[:120]}")

    settings = get_settings()
    history  = get_history(session_id)
    messages = history + [{"role": "user", "content": current_message}]

    try:
        if settings.llm_provider == "openai":
            llm = _get_llm()
            full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
            response  = llm.invoke(full_messages)
            ai_output = response.content if hasattr(response, "content") else str(response)
        else:
            ai_output = _call_ollama_direct(SYSTEM_PROMPT, messages)

        clean = re.sub(r"<think>[\s\S]*?</think>", "[think]", ai_output).strip()
        logger.info(f"Orders AI output ({len(ai_output)} chars): {clean[:200]}")
        return {**state, "ai_output": ai_output}

    except Exception as e:
        logger.error(f"Orders AI Agent error: {e}", exc_info=True)
        return {**state, "ai_output": f"Error: {str(e)}"}


def parse_output_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Parse AI Output — extract JSON from the LLM's response."""
    logger.info("=== Orders Parse Output Node ===")
    parsed = parse_ai_json(state.get("ai_output") or "")
    if parsed:
        return {**state, "parsed_json": parsed, "should_call_api": True}
    return {**state, "parsed_json": None, "should_call_api": False}


def db_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Database node — builds and executes sp_orders().

    Orders sql_builder takes an extra raw_message argument used to recover
    missing fields (productId, productPricingId, orderDate) from the original
    message text when the structured params are incomplete.
    """
    logger.info("=== Orders Database Node ===")
    try:
        parsed_json = state.get("parsed_json") or {}
        if not parsed_json:
            return {**state, "db_rows": []}

        raw_message = state.get("raw_message") or state.get("user_input", "")
        query, _ = build_orders_query(dict(parsed_json), raw_message)
        logger.info(f"Built sp_orders query — mode={parsed_json.get('mode')} action={parsed_json.get('action', '')}")

        db_rows = execute_sp(query)
        logger.info(f"sp_orders returned {len(db_rows)} rows")
        return {**state, "db_rows": db_rows}

    except ValueError as e:
        # Validation error from sql_builder — surface cleanly
        logger.error(f"Orders SQL validation error: {e}")
        return {**state, "db_rows": [{"result": {
            "metadata": {"status": "error", "code": -1, "message": str(e)}
        }}]}
    except Exception as e:
        logger.error(f"Orders database error: {e}", exc_info=True)
        return {**state, "db_rows": [{"result": {
            "metadata": {"status": "error", "code": -500, "message": f"Database error: {str(e)}"}
        }}]}


def formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Formatter node — formats output (returns dict) and persists turn to memory.

    Orders formatter returns a dict with keys:
        output, mode, reportMode, entity, success,
        and optionally: order_id, order_number, result, context
    """
    logger.info("=== Orders Formatter Node ===")
    try:
        if state.get("should_call_api"):
            db_rows     = state.get("db_rows") or []
            parsed_json = state.get("parsed_json") or {}
            fmt_result  = format_response(db_rows, parsed_json)
            final_output = fmt_result.get("output", "")
            logger.info(
                f"Orders formatted — mode={fmt_result.get('mode')} "
                f"entity={fmt_result.get('entity')} len={len(final_output)}"
            )
        else:
            ai_output = state.get("ai_output") or "No response generated"
            fmt_result = {
                "output":     ai_output,
                "mode":       "conversational",
                "reportMode": "conversational",
                "entity":     "orders",
                "success":    True,
            }
            final_output = ai_output
            logger.info("Orders returning conversational response")

        # Persist to session memory
        session_id = state.get("session_id", "default-session")
        user_input = state.get("user_input", "")
        if user_input and final_output:
            save_turn(session_id, user_input, final_output)

        return {**state, "format_result": fmt_result, "final_output": final_output}

    except Exception as e:
        logger.error(f"Orders formatter error: {e}", exc_info=True)
        err = {
            "output":     f"Error formatting response: {str(e)}",
            "mode":       "error",
            "reportMode": "error",
            "entity":     "orders",
            "success":    False,
        }
        return {**state, "format_result": err, "final_output": err["output"]}


# ============================================================================
# GRAPH SINGLETON
# ============================================================================

_graph_app = None


def get_graph():
    global _graph_app
    if _graph_app is None:
        _graph_app = build_graph_with_schema(
            state_schema=OrderAgentState,
            pre_router_node=pre_router_node,
            ai_agent_node=ai_agent_node,
            parse_output_node=parse_output_node,
            db_node=db_node,
            formatter_node=formatter_node,
            graph_label="Orders Agent",
        )
    return _graph_app
