"""FastAPI router for browser speech-to-text via Azure Cognitive Services.

The Azure Speech subscription key cannot live in client JS, so this module
mints short-lived (10-minute) authorization tokens that the browser uses
with the Azure Speech JS SDK. The SDK then talks directly to
wss://<region>.stt.speech.microsoft.com — same engine bing.com uses.

Setup
-----
1. Provision an Azure Speech resource.
   Free tier: 5 audio-hours/month STT, then ~$1/audio-hour.
2. Set environment variables in Railway (or .env locally):
       AZURE_SPEECH_KEY=<your subscription key>
       AZURE_SPEECH_REGION=<region, e.g. eastus, westus2, westeurope>
3. The frontend Azure SDK loads via CDN and uses the token from this
   endpoint. If env vars are not set, /voice/azure-token returns 503
   and the frontend falls back to the browser's built-in Web Speech API.

Endpoints
---------
  GET  /voice-health         — reports whether Azure is configured.
  POST /voice/azure-token    — mints a short-lived auth token + region.

v1.0.0 — initial implementation
"""

import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Azure tokens are valid for 10 minutes. Cache server-side so we don't
# hit the STS endpoint on every browser click.
_TOKEN_CACHE: dict = {"token": None, "region": None, "expires_at": 0.0}
_TOKEN_TTL_SECONDS = 9 * 60   # refresh 1 min before expiry


def _credentials() -> tuple[Optional[str], str]:
    key = (settings.azure_speech_key or "").strip()
    region = (settings.azure_speech_region or "eastus").strip() or "eastus"
    return (key or None, region)


@router.get("/voice-health")
def voice_health() -> dict:
    key, region = _credentials()
    return {
        "ok": True,
        "azure_configured": bool(key),
        "region": region if key else None,
    }


@router.post("/voice/azure-token")
def issue_azure_speech_token() -> dict:
    """Mint a short-lived Azure Speech authorization token.

    Returns
    -------
    {"token": "<jwt>", "region": "<azure region>"}
    """
    key, region = _credentials()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Azure Speech not configured. Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.",
        )

    now = time.time()
    cached = _TOKEN_CACHE
    if (
        cached["token"]
        and cached["region"] == region
        and cached["expires_at"] - now > 60
    ):
        return {"token": cached["token"], "region": cached["region"]}

    sts_url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                sts_url,
                headers={
                    "Ocp-Apim-Subscription-Key": key,
                    "Content-Length": "0",
                },
            )
        resp.raise_for_status()
        token = resp.text.strip()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Azure issueToken failed: %s — %s", e.response.status_code, e.response.text[:200]
        )
        raise HTTPException(status_code=502, detail="Azure token request rejected.")
    except httpx.RequestError as e:
        logger.error("Azure issueToken network error: %s", e)
        raise HTTPException(status_code=502, detail="Azure token network error.")

    if not token:
        raise HTTPException(status_code=502, detail="Azure returned an empty token.")

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["region"] = region
    _TOKEN_CACHE["expires_at"] = now + _TOKEN_TTL_SECONDS
    return {"token": token, "region": region}
