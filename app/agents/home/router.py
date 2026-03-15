"""FastAPI router for the Home Index dashboard endpoint.

Endpoint: GET /home-index

Calls sp_home_index() directly — a single round-trip that returns all four
KPI cards for the home page in one response.  No AI / LangGraph involved;
this is a purely deterministic stored-procedure call.

Query parameters (all optional):
    owner_id        UUID — scope pipeline & leads to one owner
    employee_uuid   UUID — scope notifications to one employee

Response mirrors the sp_home_index JSONB document shape:
    active_pipeline  { count, total_amount, weighted_amount }
    open_leads       { count, by_status[] }
    pending_orders   { count, by_status[] }
    unread_alerts    { count, delta, yesterday }
    metadata         { status, code, generated_at, filters }
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.database import execute_sp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Home"])


# ============================================================================
# RESPONSE MODEL
# ============================================================================

class KpiPipeline(BaseModel):
    label:           str
    sublabel:        str
    count:           int
    total_amount:    float
    weighted_amount: float

class KpiLeads(BaseModel):
    label:     str
    sublabel:  str
    count:     int
    by_status: list

class KpiOrders(BaseModel):
    label:     str
    sublabel:  str
    count:     int
    by_status: list

class KpiAlerts(BaseModel):
    label:             str
    sublabel:          str
    count_30d:         int       # total unread in last 30 days (headline)
    count_today:       int       # unread created today
    count_yesterday:   int       # unread created yesterday
    delta_today:       int       # count_today minus count_yesterday
    by_day:            list      # 30-entry [{day, count}] sparkline

class HomeIndexMetadata(BaseModel):
    status:       str
    code:         int
    generated_at: str
    filters:      dict

class HomeIndexResponse(BaseModel):
    metadata:        HomeIndexMetadata
    active_pipeline: KpiPipeline
    open_leads:      KpiLeads
    pending_orders:  KpiOrders
    unread_alerts:   KpiAlerts
    success:         bool = True


# ============================================================================
# SQL BUILDER
# ============================================================================

def _build_home_index_query(
    owner_id:       Optional[str],
    employee_uuid:  Optional[str],
) -> str:
    """
    Build the sp_home_index() call with only the params the caller supplied.
    Named-parameter style matches every other sql_builder in the project.
    """
    parts = []

    if owner_id:
        safe = owner_id.strip().replace("'", "")
        parts.append(f"p_owner_id := '{safe}'::UUID")

    if employee_uuid:
        safe = employee_uuid.strip().replace("'", "")
        parts.append(f"p_employee_uuid := '{safe}'::UUID")

    args = ", ".join(parts) if parts else ""
    return f"SELECT sp_home_index({args}) AS result;"


# ============================================================================
# ROUTES
# ============================================================================

@router.get("/home-index", response_model=HomeIndexResponse)
async def home_index(
    owner_id:       Optional[str] = Query(default=None, description="Scope pipeline & leads to one owner UUID"),
    employee_uuid:  Optional[str] = Query(default=None, description="Scope notifications to one employee UUID"),
):
    """
    Home dashboard KPI endpoint — calls sp_home_index() and returns all four
    KPI cards (active pipeline, open leads, pending orders, unread alerts)
    in a single database round-trip.

    Called immediately on page load by crm_index.html.
    """
    logger.info("=== Home Index Request ===")
    logger.info(f"owner_id={owner_id!r}  employee_uuid={employee_uuid!r}")

    try:
        query = _build_home_index_query(owner_id, employee_uuid)
        logger.debug(f"SQL: {query}")

        rows = execute_sp(query)

        if not rows:
            raise ValueError("sp_home_index returned no rows")

        data: Dict[str, Any] = rows[0].get("result") or {}

        # Surface any SP-level error cleanly
        meta = data.get("metadata", {})
        if meta.get("status") == "error":
            logger.error(f"sp_home_index error: {meta.get('message')}")
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {meta.get('message', 'unknown')}",
            )

        logger.info(
            f"Home index OK — "
            f"pipeline={data.get('active_pipeline', {}).get('count')} "
            f"leads={data.get('open_leads', {}).get('count')} "
            f"orders={data.get('pending_orders', {}).get('count')} "
            f"alerts={data.get('unread_alerts', {}).get('count_30d')}"
        )

        # Build typed response — provide safe defaults for every field so the
        # page always renders something even if the DB returns partial data.
        def _kpi_pipeline(d: dict) -> dict:
            return {
                "label":           d.get("label",           "Active pipeline"),
                "sublabel":        d.get("sublabel",         "open opportunities"),
                "count":           int(d.get("count",           0) or 0),
                "total_amount":    float(d.get("total_amount",    0) or 0),
                "weighted_amount": float(d.get("weighted_amount", 0) or 0),
            }

        def _kpi_simple(d: dict, label: str, sublabel: str) -> dict:
            return {
                "label":     d.get("label",    label),
                "sublabel":  d.get("sublabel", sublabel),
                "count":     int(d.get("count", 0) or 0),
                "by_status": d.get("by_status", []) or [],
            }

        def _kpi_alerts(d: dict) -> dict:
            return {
                "label":           d.get("label",           "Unread alerts"),
                "sublabel":        d.get("sublabel",         "past 30 days"),
                "count_30d":       int(d.get("count_30d",       0) or 0),
                "count_today":     int(d.get("count_today",     0) or 0),
                "count_yesterday": int(d.get("count_yesterday", 0) or 0),
                "delta_today":     int(d.get("delta_today",     0) or 0),
                "by_day":          d.get("by_day",               []) or [],
            }

        return HomeIndexResponse(
            metadata=HomeIndexMetadata(
                status=       meta.get("status",       "success"),
                code=         int(meta.get("code",     0) or 0),
                generated_at= meta.get("generated_at", ""),
                filters=      meta.get("filters",      {}),
            ),
            active_pipeline= KpiPipeline(**_kpi_pipeline(data.get("active_pipeline", {}))),
            open_leads=      KpiLeads(**_kpi_simple(data.get("open_leads",    {}), "Open leads",     "awaiting qualification")),
            pending_orders=  KpiOrders(**_kpi_simple(data.get("pending_orders",{}), "Pending orders", "processing & ready")),
            unread_alerts=   KpiAlerts(**_kpi_alerts(data.get("unread_alerts",  {}))),
            success=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Home index error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
