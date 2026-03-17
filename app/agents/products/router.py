"""FastAPI router for the Products domain.

Endpoint: POST /prod-chat
Version:  2.0.0

Drop-in replacement for the standalone product_agent /prod-chat endpoint.
The request/response shape is identical to the original.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.graph_utils import AgentState
from .graph import get_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Products"])


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class ProductData(BaseModel):
    """Structured product payload for product_direct_operation."""
    context:         Optional[str]   = None   # 'create_product' | 'update_product'
    product_id:      Optional[str]   = None
    product_number:  Optional[int]   = None   # for price history by number
    name:            Optional[str]   = None
    sku:             Optional[str]   = None
    category_id:     Optional[str]   = None
    category_num:    Optional[int]   = None
    category_name:   Optional[str]   = None
    retail_price:    Optional[float] = None
    promo_price:     Optional[float] = None
    wholesale_price: Optional[float] = None
    stock_quantity:  Optional[int]   = None
    description:     Optional[str]   = None
    status:          Optional[str]   = None
    created_by:      Optional[str]   = None
    updated_by:      Optional[str]   = None


class ProductChatInput(BaseModel):
    """All chatInput fields used by the Product pre-router and web page v11.0+."""
    message:      Optional[str]  = None   # optional — AI chat path only
    mode:         Optional[str]  = None   # direct SP route
    routerAction: Optional[bool] = None   # True → bypass AI agent

    # ── Direct operation payload ───────────────────────────────────────────────
    productData:       Optional[ProductData] = None

    # ── List / search filters ─────────────────────────────────────────────────
    search:            Optional[str]   = None
    nameFilter:        Optional[str]   = None
    skuFilter:         Optional[str]   = None
    categoryFilter:    Optional[str]   = None
    categoryNumber:    Optional[int]   = None
    categoryNum:       Optional[int]   = None
    isActiveFilter:    Optional[bool]  = None

    # ── Pagination / sorting ──────────────────────────────────────────────────
    pageSize:          Optional[int]   = None
    pageNumber:        Optional[int]   = None
    sortField:         Optional[str]   = None
    sortOrder:         Optional[str]   = None

    # ── Single-product lookup ─────────────────────────────────────────────────
    productId:         Optional[str]   = None
    productNumber:     Optional[int]   = None
    sku:               Optional[str]   = None

    # ── Pricing ───────────────────────────────────────────────────────────────
    wholesalePrice:    Optional[float] = None
    retailPrice:       Optional[float] = None
    promoPrice:        Optional[float] = None
    priceType:         Optional[str]   = None
    priceValue:        Optional[float] = None
    currency:          Optional[str]   = None

    # ── Inventory ─────────────────────────────────────────────────────────────
    stock:             Optional[int]   = None
    stockAdjustment:   Optional[int]   = None
    lowStockThreshold: Optional[int]   = None

    # ── Audit ─────────────────────────────────────────────────────────────────
    isActive:          Optional[bool]  = None
    status:            Optional[str]   = None
    createdBy:         Optional[str]   = None
    updatedBy:         Optional[str]   = None
    description:       Optional[str]   = None


class ProductChatRequest(BaseModel):
    chatInput: ProductChatInput
    sessionId: Optional[str] = "default-session"


class ProductChatResponse(BaseModel):
    sessionId:      str
    output:         str
    rawParams:      Optional[dict] = None
    calledDatabase: bool = False
    mode:           Optional[str] = None
    reportMode:     Optional[str] = None
    success:        bool = True


_REPORT_MODE_MAP = {
    "list":               "list",
    "get_details":        "get_details",
    "add":                "add_confirmation",
    "create":             "add_confirmation",
    "update":             "update_confirmation",
    "bulk_adjust_stock":  "bulk_adjust_stock",
    "inventory_summary":  "inventory_summary",
    "low_stock":          "low_stock",
    "price_history":      "price_history",
    "price_matrix":       "price_matrix",
    "product_search":     "product_search",
}


# ============================================================================
# ROUTES
# ============================================================================

@router.get("/product-health")
async def product_health():
    return {
        "status":  "healthy",
        "module":  "products",
        "version": "2.0.0",
        "graph_initialized": get_graph() is not None,
    }


@router.post("/prod-chat", response_model=ProductChatResponse)
async def product_chat(req: ProductChatRequest):
    """
    Main products endpoint — drop-in replacement for the standalone
    product_agent /prod-chat webhook.
    """
    logger.info("=== New Product Chat Request ===")
    session_id = (req.sessionId or "default-session").strip()
    ci = req.chatInput
    logger.info(f"Session: {session_id}  Message: {(ci.message or "")[:120]}")

    chat_input: Dict[str, Any] = ci.model_dump(exclude_none=True)
    chat_input["message"] = ci.message or ""
    if ci.productData:
        chat_input["productData"] = ci.productData.model_dump(exclude_none=True)

    try:
        graph_app = get_graph()

        initial_state: AgentState = {
            "session_id":      session_id,
            "chat_input":      chat_input,
            "user_input":      ci.message or "",
            "router_action":   False,
            "ai_output":       None,
            "parsed_json":     None,
            "should_call_api": False,
            "db_rows":         None,
            "final_output":    None,
        }

        final_state  = graph_app.invoke(initial_state)
        raw_params   = final_state.get("parsed_json")
        called_db    = final_state.get("should_call_api", False)
        mode         = (raw_params.get("mode") or "unknown") if raw_params else "unknown"
        report_mode  = _REPORT_MODE_MAP.get(mode, "generic")
        final_output = final_state.get("final_output") or ""

        logger.info(f"Products request complete — DB={called_db}, mode={mode}")

        return ProductChatResponse(
            sessionId=session_id,
            output=final_output,
            rawParams=raw_params,
            calledDatabase=called_db,
            mode=mode,
            reportMode=report_mode,
            success=True,
        )

    except Exception as e:
        logger.error(f"Product chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
