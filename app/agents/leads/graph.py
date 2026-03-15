"""LangGraph agent module for the Leads domain.

State matches Activities (body + current_message + format_result).
route_request(body, chat_input, session_id) — 3-arg.
format_response(db_rows, params) — returns Dict[str, Any] with rich
side-channel fields: leads, lead, pipeline, employees, account, contact,
opportunity, address, accountId, contactId, opportunityId.
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

from .prompt import LEAD_AGENT_SYSTEM_PROMPT
from .pre_router import route_request
from .sql_builder import build_leads_query
from .formatter import format_response

logger = logging.getLogger(__name__)


# ============================================================================
# EXTENDED STATE  (matches Activities pattern)
# ============================================================================

class LeadAgentState(TypedDict):
    session_id:       str
    body:             dict
    chat_input:       dict
    user_input:       str
    current_message:  str
    router_action:    bool
    ai_output:        Optional[str]
    parsed_json:      Optional[Dict[str, Any]]
    should_call_api:  bool
    db_rows:          Optional[List]
    format_result:    Optional[Dict[str, Any]]
    final_output:     Optional[str]


# ============================================================================
# NODES
# ============================================================================

def pre_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-Router — prefix-based routing (matches Activities pattern)."""
    logger.info("=== Leads Pre-Router Node ===")
    body       = state.get("body", {})
    chat_input = state.get("chat_input", {})
    session_id = state.get("session_id", "")
    logger.info(f"Message: {chat_input.get('message', '')[:120]}")

    result = route_request(body, chat_input, session_id)

    if result["router_action"]:
        params = result["params"]
        logger.info(f"Leads pre-router ROUTED → mode={params.get('mode')}")
        return {
            **state,
            "router_action":   True,
            "parsed_json":     params,
            "should_call_api": True,
            "current_message": state.get("user_input", ""),
        }

    current_msg = result.get("current_message", state.get("user_input", ""))
    logger.info(f"Leads pre-router PASSTHRU → {current_msg[:80]}")
    return {**state, "router_action": False, "current_message": current_msg}


def ai_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """AI Agent node — invokes LLM with the leads system prompt."""
    logger.info("=== Leads AI Agent Node ===")
    session_id      = state.get("session_id", "default-session")
    current_message = state.get("current_message") or state.get("user_input", "")

    settings = get_settings()
    history  = get_history(session_id)
    messages = history + [{"role": "user", "content": current_message}]

    try:
        if settings.llm_provider == "openai":
            llm = _get_llm()
            full_messages = [{"role": "system", "content": LEAD_AGENT_SYSTEM_PROMPT}] + messages
            response  = llm.invoke(full_messages)
            ai_output = response.content if hasattr(response, "content") else str(response)
        else:
            ai_output = _call_ollama_direct(LEAD_AGENT_SYSTEM_PROMPT, messages)

        clean = re.sub(r"<think>[\s\S]*?</think>", "[think]", ai_output).strip()
        logger.info(f"Leads AI output ({len(ai_output)} chars): {clean[:200]}")
        return {**state, "ai_output": ai_output}

    except Exception as e:
        logger.error(f"Leads AI Agent error: {e}", exc_info=True)
        return {**state, "ai_output": f"Error: {str(e)}"}


def parse_output_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Parse AI Output — extract JSON from the LLM's response."""
    logger.info("=== Leads Parse Output Node ===")
    parsed = parse_ai_json(state.get("ai_output") or "")
    if parsed:
        return {**state, "parsed_json": parsed, "should_call_api": True}
    return {**state, "parsed_json": None, "should_call_api": False}


def db_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Database node — builds and executes sp_leads()."""
    logger.info("=== Leads Database Node ===")
    try:
        parsed_json = state.get("parsed_json") or {}
        if not parsed_json:
            return {**state, "db_rows": []}

        query, _ = build_leads_query(parsed_json)
        logger.info(f"Built sp_leads query for mode: {parsed_json.get('mode')}")

        db_rows = execute_sp(query)
        logger.info(f"sp_leads returned {len(db_rows)} rows")
        return {**state, "db_rows": db_rows}

    except Exception as e:
        logger.error(f"Leads database error: {e}", exc_info=True)
        return {**state, "db_rows": [{"result": {
            "metadata": {"status": "error", "code": -500, "message": str(e)}
        }}]}


def formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Formatter node — formats output (dict) and persists turn to memory."""
    logger.info("=== Leads Formatter Node ===")
    try:
        if state.get("should_call_api"):
            db_rows     = state.get("db_rows") or []
            parsed_json = state.get("parsed_json") or {}
            fmt_result  = format_response(db_rows, parsed_json)
            final_output = fmt_result.get("output", "")
            logger.info(f"Leads formatted — mode={fmt_result.get('mode')} len={len(final_output)}")
        else:
            ai_output  = state.get("ai_output") or "No response generated"
            fmt_result = {
                "output":      ai_output,
                "mode":        "conversational",
                "report_mode": "conversational",
                "success":     True,
            }
            final_output = ai_output

        session_id = state.get("session_id", "default-session")
        user_input = state.get("user_input", "")
        if user_input and final_output:
            save_turn(session_id, user_input, final_output)

        return {**state, "format_result": fmt_result, "final_output": final_output}

    except Exception as e:
        logger.error(f"Leads formatter error: {e}", exc_info=True)
        err = {"output": f"Error: {str(e)}", "mode": "error",
               "report_mode": "error", "success": False}
        return {**state, "format_result": err, "final_output": err["output"]}


# ============================================================================
# GRAPH SINGLETON
# ============================================================================

_graph_app = None


def get_graph():
    global _graph_app
    if _graph_app is None:
        _graph_app = build_graph_with_schema(
            state_schema=LeadAgentState,
            pre_router_node=pre_router_node,
            ai_agent_node=ai_agent_node,
            parse_output_node=parse_output_node,
            db_node=db_node,
            formatter_node=formatter_node,
            graph_label="Leads Agent",
        )
    return _graph_app
