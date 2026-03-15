"""Shared LLM factory and graph building utilities for all CRM Agent modules.

Every agent graph imports _get_llm(), _call_ollama_direct(), and the shared
AgentState TypedDict from this module.  Agent-specific nodes (pre_router,
ai_agent, db, format) are wired in each agent's own graph.py.

Adding a new agent
------------------
1. Import AgentState, _get_llm, _call_ollama_direct, build_standard_graph
   in the new agent's graph.py.
2. Define pre_router_node, ai_agent_node, db_node, formatter_node.
3. Call build_standard_graph(nodes_dict) to get a compiled graph.
   Or wire a custom topology if the agent needs non-standard edges.
"""

from __future__ import annotations

import json
import re
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
try:
    from langchain_ollama import ChatOllama
except ImportError:
    from langchain_community.chat_models import ChatOllama

from .config import get_settings

logger = logging.getLogger(__name__)


# ============================================================================
# SHARED STATE DEFINITION
# All agent graphs use this same TypedDict — ensures consistent state keys.
# ============================================================================

class AgentState(TypedDict):
    session_id:      str
    chat_input:      dict           # raw chatInput fields forwarded from the request
    user_input:      str            # message string (raw or preprocessed)
    router_action:   bool           # True = pre-router hit → skip AI Agent
    ai_output:       Optional[str]
    parsed_json:     Optional[Dict[str, Any]]
    should_call_api: bool
    db_rows:         Optional[List]
    final_output:    Optional[str]


# ============================================================================
# LLM FACTORY
# ============================================================================

def _get_llm():
    """Return the configured LLM (OpenAI or Ollama ChatModel)."""
    settings = get_settings()
    if settings.llm_provider == "openai":
        logger.info(f"Using OpenAI LLM: {settings.llm_model}")
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            temperature=0.1,
        )
    logger.info(f"Using Ollama LLM: {settings.llm_model}")
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
        temperature=0.1,
    )


def _call_ollama_direct(system_prompt: str, messages: list) -> str:
    """
    Direct Ollama /api/chat call — bypasses ChatOllama which can silently
    drop the ``thinking`` field from reasoning models (Qwen / gpt-oss /
    DeepSeek-R1).

    Falls back to the ``thinking`` field if ``content`` is empty, matching
    the pattern needed for chain-of-thought models that place their JSON
    answer inside <think> blocks.
    """
    import httpx
    settings = get_settings()

    payload = {
        "model":    settings.ollama_model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream":   False,
        "options":  {"temperature": 0.1},
    }

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/chat",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()

    msg      = data.get("message", {})
    content  = msg.get("content",  "") or ""
    thinking = msg.get("thinking", "") or ""

    logger.info(f"Ollama direct — content: {len(content)} chars, thinking: {len(thinking)} chars")

    if content.strip():
        return content
    if thinking.strip():
        logger.info("Content empty — using thinking field")
        return thinking
    logger.warning("Ollama returned empty content AND empty thinking")
    return ""


# ============================================================================
# JSON PARSER UTILITIES  (shared by all parse_output_node implementations)
# ============================================================================

def extract_json_objects(text: str) -> list:
    """
    Stack-based extractor — handles nested JSON objects correctly.
    Mirrors the n8n Parse AI Output extractJsonObjects() function.
    """
    results = []
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                results.append(text[start: i + 1])
                start = -1
    return results


def parse_ai_json(ai_output: str) -> Optional[Dict[str, Any]]:
    """
    Extract the last valid JSON object containing a ``mode`` key from the
    AI output string.

    Strategy (mirrors n8n Parse AI Output Code node):
      1. Stack-based extraction — walk from END, pick last valid JSON with mode
      2. Markdown code block fallback
      3. Last {...} block regex fallback

    Returns the parsed dict, or None if no valid JSON with mode was found.
    """
    if not ai_output:
        return None

    # 1. Stack-based
    candidates = extract_json_objects(ai_output)
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if parsed.get("mode"):
                logger.info(f"Parsed JSON via stack-extractor: mode={parsed['mode']}")
                return parsed
        except json.JSONDecodeError:
            pass

    # 2. Markdown code block
    md_match = re.search(r'```json\s*([\s\S]*?)```', ai_output)
    if md_match:
        try:
            parsed = json.loads(md_match.group(1).strip())
            if parsed.get("mode"):
                logger.info(f"Parsed JSON via markdown block: mode={parsed['mode']}")
                return parsed
        except json.JSONDecodeError:
            pass

    # 3. Last {...} block regex
    last_match = re.search(r'(\{[^{}]*\})\s*$', ai_output)
    if last_match:
        try:
            parsed = json.loads(last_match.group(1))
            if parsed.get("mode"):
                logger.info(f"Parsed JSON via last-brace regex: mode={parsed['mode']}")
                return parsed
        except json.JSONDecodeError:
            pass

    logger.info("No valid JSON with mode found — conversational response")
    return None


# ============================================================================
# STANDARD GRAPH BUILDER
# Wires the canonical 5-node topology shared by all current agents.
# Agents with non-standard topology should build their own graph instead.
# ============================================================================

def build_standard_graph(
    pre_router_node,
    ai_agent_node,
    parse_output_node,
    db_node,
    formatter_node,
    graph_label: str = "CRM Agent",
) -> object:
    """
    Build and compile the standard LangGraph topology:

        pre_router ─┬─[direct_db]──→ db ──→ format → END
                    └─[ai_agent]──→ ai_agent → parse ─┬─[call_db]──→ db → format → END
                                                       └─[skip_db]──→ format → END

    Parameters
    ----------
    pre_router_node   : callable(state) → state
    ai_agent_node     : callable(state) → state
    parse_output_node : callable(state) → state
    db_node           : callable(state) → state
    formatter_node    : callable(state) → state
    graph_label       : Human-readable name for log messages.
    """
    logger.info(f"Building {graph_label} LangGraph...")

    def _route_after_pre_router(state):
        if state.get("router_action"):
            return "direct_db"
        return "ai_agent"

    def _route_after_parse(state):
        if state.get("should_call_api"):
            return "call_db"
        return "skip_db"

    graph = StateGraph(AgentState)
    graph.add_node("pre_router", pre_router_node)
    graph.add_node("ai_agent",   ai_agent_node)
    graph.add_node("parse",      parse_output_node)
    graph.add_node("db",         db_node)
    graph.add_node("format",     formatter_node)

    graph.set_entry_point("pre_router")
    graph.add_conditional_edges(
        "pre_router",
        _route_after_pre_router,
        {"direct_db": "db", "ai_agent": "ai_agent"},
    )
    graph.add_edge("ai_agent", "parse")
    graph.add_conditional_edges(
        "parse",
        _route_after_parse,
        {"call_db": "db", "skip_db": "format"},
    )
    graph.add_edge("db",     "format")
    graph.add_edge("format", END)

    logger.info(f"{graph_label} LangGraph built successfully")
    return graph.compile()


# ============================================================================
# EXTENDED-STATE GRAPH BUILDER (for agents with extra state keys e.g. Orders)
# Same topology as build_standard_graph but accepts a custom state_schema.
# ============================================================================

def build_graph_with_schema(
    state_schema,
    pre_router_node,
    ai_agent_node,
    parse_output_node,
    db_node,
    formatter_node,
    graph_label: str = "CRM Agent",
) -> object:
    """
    Same canonical 5-node topology as build_standard_graph but the caller
    supplies the TypedDict class used for StateGraph(schema).

    Use this when your agent needs extra state keys beyond the base AgentState
    (e.g. the Orders agent adds body, current_message, raw_message, params,
    format_result).
    """
    logger.info(f"Building {graph_label} LangGraph (custom schema)...")

    def _route_after_pre_router(state):
        return "direct_db" if state.get("router_action") else "ai_agent"

    def _route_after_parse(state):
        return "call_db" if state.get("should_call_api") else "skip_db"

    graph = StateGraph(state_schema)
    graph.add_node("pre_router", pre_router_node)
    graph.add_node("ai_agent",   ai_agent_node)
    graph.add_node("parse",      parse_output_node)
    graph.add_node("db",         db_node)
    graph.add_node("format",     formatter_node)

    graph.set_entry_point("pre_router")
    graph.add_conditional_edges(
        "pre_router", _route_after_pre_router,
        {"direct_db": "db", "ai_agent": "ai_agent"},
    )
    graph.add_edge("ai_agent", "parse")
    graph.add_conditional_edges(
        "parse", _route_after_parse,
        {"call_db": "db", "skip_db": "format"},
    )
    graph.add_edge("db",     "format")
    graph.add_edge("format", END)

    logger.info(f"{graph_label} LangGraph built successfully")
    return graph.compile()
