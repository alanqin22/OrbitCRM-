"""Request preprocessor — mirrors the n8n 'Code in JavaScript' node (passthru path).

In the v7 architecture the pre_router.py module handles ALL message routing,
including building the preprocessed current_message for the AI Agent passthru
path.  This module is retained for:
  • Backward compatibility (any direct callers).
  • Testing the passthru message-building logic in isolation.

The n8n JavaScript node logic (verbatim, passthru branch):
    let message = chatInput.message || "";
    if (chatInput.city)         message += `, city ${chatInput.city}`;
    if (chatInput.pageSize)     message += `, page size ${chatInput.pageSize}`;
    if (chatInput.pageNumber)   message += `, page number ${chatInput.pageNumber}`;
    if (chatInput.customerId)   message += `, customer ID ${chatInput.customerId}`;
    return message.trim();
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def preprocess_request(
    message: str,
    session_id: str,
    city: Optional[str] = None,
    page_size: Optional[int] = None,
    page_number: Optional[int] = None,
    customer_id: Optional[str] = None,
) -> tuple[str, str]:
    """
    Build the normalised chat message by appending any structured chatInput
    fields to the natural-language message text — exactly as the n8n
    'Code in JavaScript' node does (passthru branch).

    In the v7 flow this logic is called by pre_router._build_passthru_message()
    directly.  This standalone function is kept for backward compatibility.

    Parameters
    ----------
    message      : Free-text message from chatInput.message
    session_id   : Session identifier (defaults to "default-session")
    city         : Optional city filter  → ", city <value>"
    page_size    : Optional page size    → ", page size <n>"
    page_number  : Optional page number  → ", page number <n>"
    customer_id  : Optional customer UUID → ", customer ID <uuid>"

    Returns
    -------
    (current_message, session_id) — both stripped.
    """
    current_message = message or ""

    if city:
        current_message += f", city {city}"
    if page_size is not None:
        current_message += f", page size {page_size}"
    if page_number is not None:
        current_message += f", page number {page_number}"
    if customer_id:
        current_message += f", customer ID {customer_id}"

    current_message = current_message.strip()
    session_id = (session_id or "default-session").strip()

    logger.debug(
        f"Preprocessor — session={session_id!r}, "
        f"original={message!r}, built={current_message!r}"
    )

    return current_message, session_id
