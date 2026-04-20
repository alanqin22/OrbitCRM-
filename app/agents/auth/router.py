"""FastAPI router for authentication — Orbit CRM Auth module.

Endpoints
---------
  GET  /auth-health                    — health check
  POST /auth/signup                    — register new account + credential (bcrypt)
  POST /auth/signin                    — verify credential, issue session token
  POST /auth/signout                   — invalidate session
  POST /auth/change-password           — authenticated password rotation
  POST /auth/password-reset/request    — generate single-use reset token
  POST /auth/password-reset/confirm    — consume reset token, set new password
  POST /auth/verify-email              — verify contact e-mail token

Design
------
  • No LangGraph — direct psycopg2 calls to SECURITY DEFINER functions
    defined in sql/sp_auth.sql.
  • Primary hash path: bcrypt (DB-side via pgcrypto) — zero extra Python deps.
  • Argon2id variant: set HASH_ALGO=argon2id in .env and install argon2-cffi;
    the router auto-detects and calls the _prehashed variants instead.
  • Sessions: in-process dict keyed by a 32-byte URL-safe token.
    For multi-worker deployments, swap _AUTH_SESSIONS for Redis.

DB functions used (all SECURITY DEFINER, owned by auth_owner)
--------------------------------------------------------------
  create_credential               — bcrypt signup
  verify_credential               — bcrypt signin
  change_password                 — bcrypt password rotation
  create_credential_prehashed     — Argon2id signup
  verify_credential_prehashed     — Argon2id signin  (app verifies via PH.verify)
  change_password_prehashed       — Argon2id rotation
  create_password_reset_token     — token generation
  consume_password_reset_token    — bcrypt reset
  create_email_verification_token — email verification token
  verify_email_token              — email verification confirm

v1.0.0 — initial implementation
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import psycopg2
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.core.database import get_connection
from app.agents.email.smtp_imap import send_email

# Verification code settings
_CODE_TTL_MINUTES = 15   # code expires after this many minutes
_MAX_ATTEMPTS     = 5    # wrong-code attempts before lockout
_MAX_RESENDS      = 5    # max resend requests per pending signup

# In-process store for signups awaiting 6-digit code verification
# { token: { identifier, password, first_name, ..., code, code_expires_at, attempts, resend_count } }
_PENDING_SIGNUPS: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Auth"])

# ---------------------------------------------------------------------------
# Optional Argon2id support — only imported when HASH_ALGO=argon2id
# ---------------------------------------------------------------------------
_HASH_ALGO = os.getenv("HASH_ALGO", "bcrypt").lower()
_ARGON2_PARAMS: Dict[str, Any] = {
    "memory_kib": 65536,
    "iterations": 2,
    "parallelism": 1,
}

if _HASH_ALGO == "argon2id":
    try:
        from argon2 import PasswordHasher, exceptions as _argon2_exc  # type: ignore
        _PH = PasswordHasher(
            time_cost=_ARGON2_PARAMS["iterations"],
            memory_cost=_ARGON2_PARAMS["memory_kib"],
            parallelism=_ARGON2_PARAMS["parallelism"],
            hash_len=32,
        )
        logger.info("Auth: Argon2id mode enabled")
    except ImportError:
        logger.warning("HASH_ALGO=argon2id but argon2-cffi is not installed — falling back to bcrypt")
        _HASH_ALGO = "bcrypt"
        _PH = None
        _argon2_exc = None
else:
    _PH = None
    _argon2_exc = None

# ---------------------------------------------------------------------------
# In-process session store
# { session_token: { account_id, credential_id, identifier, expires_at } }
# ---------------------------------------------------------------------------
_AUTH_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSION_TTL_HOURS = 8


def _new_session(
    account_id: str,
    credential_id: str,
    identifier: str,
    lead_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    source_table: Optional[str] = None,
) -> str:
    token = secrets.token_urlsafe(32)
    _AUTH_SESSIONS[token] = {
        "account_id":    account_id,
        "credential_id": credential_id,
        "identifier":    identifier,
        "lead_id":       lead_id,
        "contact_id":    contact_id,
        "first_name":    first_name,
        "last_name":     last_name,
        "source_table":  source_table,
        "expires_at":    datetime.now(timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS),
    }
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """Return session dict if token is valid and not expired; else None."""
    sess = _AUTH_SESSIONS.get(token)
    if sess and sess["expires_at"] > datetime.now(timezone.utc):
        return sess
    if sess:
        del _AUTH_SESSIONS[token]
    return None


def active_auth_sessions() -> int:
    """Return count of live sessions (purges expired ones as a side-effect)."""
    expired = [t for t, s in _AUTH_SESSIONS.items()
               if s["expires_at"] <= datetime.now(timezone.utc)]
    for t in expired:
        del _AUTH_SESSIONS[t]
    return len(_AUTH_SESSIONS)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SignUpRequest(BaseModel):
    identifier:     str            # email (used as login identifier, stored lowercase)
    password:       str
    confirm_password: Optional[str] = None
    # Profile fields
    first_name:     Optional[str] = None
    last_name:      Optional[str] = None
    company_name:   Optional[str] = None
    phone:          Optional[str] = None
    address_line1:  Optional[str] = None
    address_line2:  Optional[str] = None
    city:           Optional[str] = None
    province:       Optional[str] = None
    postal_code:    Optional[str] = None
    country:        Optional[str] = None
    # Legacy: supply existing IDs instead of auto-creating
    account_id:     Optional[str] = None
    contact_id:     Optional[str] = None


class SignInRequest(BaseModel):
    identifier: str
    password:   str


class SignOutRequest(BaseModel):
    session_token: str


class ChangePasswordRequest(BaseModel):
    identifier:       str
    current_password: str
    new_password:     str


class PasswordResetRequestModel(BaseModel):
    identifier:  str
    ttl_seconds: int = 3600


class PasswordResetConfirmRequest(BaseModel):
    token:        str
    new_password: str


class VerifyEmailRequest(BaseModel):
    contact_id: str
    token:      str

class VerifyCodeRequest(BaseModel):
    identifier: str
    code:       str

class ResendCodeRequest(BaseModel):
    identifier: str


class AuthResponse(BaseModel):
    success:       bool
    message:       str
    session_token: Optional[str] = None
    credential_id: Optional[str] = None
    lead_id:       Optional[str] = None
    account_id:    Optional[str] = None
    contact_id:    Optional[str] = None
    identifier:    Optional[str] = None
    email:         Optional[str] = None
    first_name:    Optional[str] = None
    last_name:     Optional[str] = None
    source_table:  Optional[str] = None
    needs_password: Optional[bool] = None
    # NOTE: reset_token is included only for development/demo mode.
    # In production, email the token to the user and remove this field.
    reset_token:   Optional[str] = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_fetchone(sql: str, params: tuple = ()) -> Any:
    """Execute SQL and return the first row (or None)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        conn.commit()
        return row
    except psycopg2.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def _db_execute(sql: str, params: tuple = ()) -> None:
    """Execute SQL with no return value."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Account / contact bootstrap helpers (used during signup)
# ---------------------------------------------------------------------------

def _bootstrap_account(company_name: str) -> str:
    """INSERT a minimal account row; return its UUID."""
    acct_id = str(uuid.uuid4())
    _db_execute(
        """
        INSERT INTO public.accounts
          (account_id, account_name, type, status, is_deleted,
           created_at, updated_at)
        VALUES (%s, %s, 'customer', 'Active', false, now(), now())
        """,
        (acct_id, company_name),
    )
    return acct_id


def _bootstrap_contact(
    account_id: str, email: str, first_name: str, last_name: str
) -> str:
    """INSERT a minimal contact row; return its UUID."""
    contact_id = str(uuid.uuid4())
    _db_execute(
        """
        INSERT INTO public.contacts
          (contact_id, account_id, first_name, last_name, email,
           status, is_deleted, is_email_verified, is_customer,
           created_at, updated_at)
        VALUES (%s, %s, %s, %s, lower(%s),
                'Active', false, false, true,
                now(), now())
        """,
        (contact_id, account_id, first_name or "", last_name or "", email),
    )
    return contact_id


# ---------------------------------------------------------------------------
# Pending signup helpers
# ---------------------------------------------------------------------------

def _find_pending_by_email(identifier: str) -> Optional[str]:
    """Return the token for a pending signup matching identifier, or None (expired entries cleaned up)."""
    now = datetime.now(timezone.utc)
    for token, data in list(_PENDING_SIGNUPS.items()):
        if data.get('identifier') == identifier:
            if data.get('code_expires_at', now) > now:
                return token
            del _PENDING_SIGNUPS[token]
    return None

def _generate_code() -> str:
    """Generate a cryptographically random 6-digit numeric code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _email_exists_in_db(identifier: str) -> bool:
    """Quick check — is this identifier already registered?"""
    try:
        row = _db_fetchone(
            "SELECT 1 FROM public.auth_credentials "
            "WHERE identifier = lower(%s) AND is_active = true LIMIT 1",
            (identifier,),
        )
        return bool(row)
    except Exception:
        return False


def _send_verification_code_email(to: str, first_name: str, code: str) -> None:
    name    = (first_name or '').strip() or 'there'
    subject = "Your 6-digit verification code — Orbit CRM"
    body_html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a202c;max-width:600px;margin:auto;padding:2rem;">
  <h2 style="color:#0d9488;">Verify your email, {name}!</h2>
  <p>Hi {name},</p>
  <p>Use the code below to verify your email address and complete your Orbit CRM sign-up.</p>
  <div style="margin:2rem 0;text-align:center;">
    <div style="display:inline-block;background:#F0FDFA;border:2px solid #0d9488;
                border-radius:12px;padding:1.25rem 2.5rem;">
      <div style="font-size:0.75rem;font-weight:600;color:#0d9488;letter-spacing:0.1em;
                  text-transform:uppercase;margin-bottom:0.5rem;">Verification Code</div>
      <div style="font-size:2.8rem;font-weight:800;letter-spacing:0.35em;color:#1a202c;
                  font-family:monospace;">{code}</div>
    </div>
  </div>
  <p style="font-size:0.85rem;color:#6b7280;">
    This code expires in <strong>{_CODE_TTL_MINUTES} minutes</strong>.<br>
    If you did not create an Orbit CRM account, you can safely ignore this email.
  </p>
  <p style="margin-top:2rem;color:#718096;font-size:0.9rem;">The Orbit CRM Team<br>
  <a href="https://agentorc.ca" style="color:#0d9488;">agentorc.ca</a></p>
</body></html>
"""
    body_text = (
        f"Hi {name},\n\n"
        f"Your Orbit CRM verification code is:\n\n  {code}\n\n"
        f"This code expires in {_CODE_TTL_MINUTES} minutes.\n\n"
        "If you did not request this, you can safely ignore this email.\n\n"
        "The Orbit CRM Team"
    )
    try:
        result = send_email(to=to, subject=subject, body_html=body_html, body_text=body_text)
        if result.get('success'):
            logger.info(f"Verification code email sent to {to}")
        else:
            logger.warning(f"Verification code email failed for {to}: {result.get('message')}")
    except Exception as exc:
        logger.error(f"Verification code email exception for {to}: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Welcome email (called in background after signup)
# ---------------------------------------------------------------------------

def _send_welcome_email(to: str, first_name: str, last_name: str) -> None:
    name = (first_name or '').strip() or 'there'
    full = f"{first_name or ''} {last_name or ''}".strip() or to
    subject = "Welcome to Orbit CRM — Your account is ready"
    body_html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a202c;max-width:600px;margin:auto;padding:2rem;">
  <h2 style="color:#4a90d9;">Welcome to Orbit CRM, {name}!</h2>
  <p>Hi {name},</p>
  <p>Your Orbit CRM account has been successfully created. You now have access to our
  full suite of CRM tools — leads, contacts, opportunities, orders, and more.</p>
  <p>Here's what you can do next:</p>
  <ul>
    <li>Browse your <strong>Dashboard</strong> for an overview</li>
    <li>Add your first <strong>Lead</strong> or <strong>Contact</strong></li>
    <li>Set up your <strong>Products</strong> and start tracking orders</li>
  </ul>
  <p>If you have any questions, simply reply to this email and our team will be happy to help.</p>
  <p>Welcome aboard!</p>
  <p style="margin-top:2rem;color:#718096;font-size:0.9rem;">The Orbit CRM Team<br>
  <a href="https://agentorc.ca" style="color:#4a90d9;">agentorc.ca</a></p>
</body></html>
"""
    body_text = (
        f"Welcome to Orbit CRM, {name}!\n\n"
        f"Hi {name},\n\n"
        "Your Orbit CRM account has been successfully created.\n\n"
        "You can now access leads, contacts, opportunities, orders, and more.\n\n"
        "Welcome aboard!\n\nThe Orbit CRM Team\nhttps://agentorc.ca"
    )
    try:
        result = send_email(to=to, subject=subject, body_html=body_html, body_text=body_text)
        if result.get('success'):
            logger.info(f"Welcome email sent to {to}")
        else:
            logger.warning(f"Welcome email failed for {to}: {result.get('message')}")
    except Exception as exc:
        logger.error(f"Welcome email exception for {to}: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/auth-health")
async def auth_health():
    return {
        "status":          "healthy",
        "module":          "auth",
        "version":         "1.0.0",
        "hash_algo":       _HASH_ALGO,
        "sessions_active": active_auth_sessions(),
    }


@router.post("/auth/signup", response_model=AuthResponse)
async def signup(req: SignUpRequest, background_tasks: BackgroundTasks):
    """Step 1 of signup: generate 6-digit code, store pending data, send code email."""
    identifier = req.identifier.strip().lower()
    logger.info(f"Signup request — identifier={identifier!r}")

    if req.confirm_password is not None and req.password != req.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")

    if _email_exists_in_db(identifier):
        raise HTTPException(status_code=409, detail="That email is already registered")

    # Re-use existing pending entry (just regenerate code)
    existing_token = _find_pending_by_email(identifier)
    if existing_token:
        p = _PENDING_SIGNUPS[existing_token]
        if p.get('resend_count', 0) >= _MAX_RESENDS:
            raise HTTPException(status_code=429, detail="Too many attempts. Please wait and try again later.")
        new_code = _generate_code()
        p['code']             = new_code
        p['code_expires_at']  = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
        p['attempts']         = 0
        p['resend_count']     = p.get('resend_count', 0) + 1
        background_tasks.add_task(_send_verification_code_email, identifier, p.get('first_name', ''), new_code)
        return AuthResponse(
            success=True,
            message=f"We've sent a 6-digit verification code to your email. Please enter it below to continue.",
            email=identifier, needs_password=False,
        )

    code  = _generate_code()
    token = secrets.token_urlsafe(32)
    _PENDING_SIGNUPS[token] = {
        'identifier':    identifier,
        'password':      req.password,
        'first_name':    req.first_name or '',
        'last_name':     req.last_name or '',
        'company_name':  req.company_name or '',
        'phone':         req.phone or '',
        'address_line1': req.address_line1 or '',
        'address_line2': req.address_line2 or '',
        'city':          req.city or '',
        'province':      req.province or '',
        'postal_code':   req.postal_code or '',
        'country':       req.country or '',
        'code':          code,
        'code_expires_at': datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES),
        'attempts':      0,
        'resend_count':  0,
    }
    background_tasks.add_task(_send_verification_code_email, identifier, req.first_name or '', code)
    logger.info(f"Pending signup + code created for {identifier!r}")

    return AuthResponse(
        success=True,
        message=f"We've sent a 6-digit verification code to your email. Please enter it below to continue.",
        email=identifier, first_name=req.first_name or '', last_name=req.last_name or '',
        needs_password=False,
    )


@router.post("/auth/verify-code", response_model=AuthResponse)
async def verify_code(req: VerifyCodeRequest, background_tasks: BackgroundTasks):
    """Step 2: validate the 6-digit code and create the account."""
    identifier = req.identifier.strip().lower()
    code       = req.code.strip()

    token = _find_pending_by_email(identifier)
    if not token:
        raise HTTPException(status_code=404, detail="No pending signup found. Please sign up again.")

    pending = _PENDING_SIGNUPS[token]
    now     = datetime.now(timezone.utc)

    if pending.get('attempts', 0) >= _MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Please request a new code.")

    if pending['code_expires_at'] <= now:
        raise HTTPException(status_code=410, detail="This code has expired. Please request a new one.")

    if pending['code'] != code:
        pending['attempts'] += 1
        remaining = _MAX_ATTEMPTS - pending['attempts']
        if remaining <= 0:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Please request a new code.")
        raise HTTPException(status_code=400, detail=f"Incorrect verification code. Please try again. ({remaining} attempt{'s' if remaining != 1 else ''} remaining)")

    # Code is valid — create the account
    if _email_exists_in_db(identifier):
        del _PENDING_SIGNUPS[token]
        raise HTTPException(status_code=409, detail="That email is already registered. Please sign in.")

    try:
        row = _db_fetchone(
            "SELECT public.sp_signup_with_lead("
            "  %s::text, %s::text,"
            "  %s::text, %s::text, %s::text, %s::text,"
            "  %s::text, %s::text, %s::text, %s::text, %s::text, %s::text"
            ") AS payload",
            (
                identifier, pending['password'],
                pending['first_name'], pending['last_name'],
                pending['company_name'], pending['phone'],
                pending['address_line1'], pending['address_line2'],
                pending['city'], pending['province'],
                pending['postal_code'], pending['country'],
            ),
        )
    except psycopg2.errors.UniqueViolation:
        del _PENDING_SIGNUPS[token]
        raise HTTPException(status_code=409, detail="That email is already registered. Please sign in.")
    except psycopg2.Error as exc:
        logger.error(f"verify-code sp_signup_with_lead error: {exc}")
        raise HTTPException(status_code=500, detail="Account creation failed. Please try again.")

    if not row or not row[0] or not row[0].get('success'):
        raise HTTPException(status_code=500, detail="Account creation failed. Please try again.")

    payload       = row[0]
    credential_id = str(payload["credential_id"])
    lead_id       = str(payload["lead_id"])    if payload.get("lead_id")    else None
    account_id    = str(payload["account_id"]) if payload.get("account_id") else None
    contact_id    = str(payload["contact_id"]) if payload.get("contact_id") else None
    first_name    = pending.get('first_name', '')
    last_name     = pending.get('last_name', '')
    source_table  = payload.get("source_table", "leads")

    del _PENDING_SIGNUPS[token]
    background_tasks.add_task(_send_welcome_email, identifier, first_name, last_name)
    logger.info(f"Code verified + account created for {identifier!r}")

    session_token = _new_session(
        account_id=account_id or '', credential_id=credential_id,
        identifier=identifier, lead_id=lead_id, contact_id=contact_id,
        first_name=first_name, last_name=last_name, source_table=source_table,
    )
    return AuthResponse(
        success=True,
        message="Email verified! Welcome to Orbit CRM.",
        session_token=session_token, credential_id=credential_id,
        lead_id=lead_id, account_id=account_id, contact_id=contact_id,
        identifier=identifier, email=identifier,
        first_name=first_name, last_name=last_name, source_table=source_table,
    )


@router.post("/auth/resend-verification", response_model=AuthResponse)
async def resend_verification(req: ResendCodeRequest, background_tasks: BackgroundTasks):
    """Resend a new 6-digit verification code, invalidating the previous one."""
    identifier = req.identifier.strip().lower()
    token      = _find_pending_by_email(identifier)

    if not token:
        return AuthResponse(success=True, message="If that email has a pending signup, a new code has been sent.")

    pending = _PENDING_SIGNUPS[token]
    if pending.get('resend_count', 0) >= _MAX_RESENDS:
        raise HTTPException(status_code=429, detail="Too many resend requests. Please wait and try again later.")

    new_code = _generate_code()
    pending['code']            = new_code
    pending['code_expires_at'] = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    pending['attempts']        = 0
    pending['resend_count']    = pending.get('resend_count', 0) + 1

    background_tasks.add_task(_send_verification_code_email, identifier, pending.get('first_name', ''), new_code)
    logger.info(f"New verification code sent for {identifier!r} (resend #{pending['resend_count']})")

    return AuthResponse(success=True, message="A new verification code has been sent to your email.", email=identifier)


@router.post("/auth/signin", response_model=AuthResponse)
async def signin(req: SignInRequest):
    """Verify credential via sp_signin_multi_table (leads → accounts → contacts lookup)."""
    identifier = req.identifier.strip().lower()
    logger.info(f"Signin — identifier={identifier!r}")

    try:
        row = _db_fetchone(
            "SELECT public.sp_signin_multi_table(%s::text, %s::text) AS payload",
            (identifier, req.password),
        )
    except psycopg2.Error as exc:
        logger.error(f"sp_signin_multi_table DB error: {exc}")
        raise HTTPException(status_code=500, detail="Authentication error")

    if not row or not row[0]:
        # Check if email is pending verification
        if _find_pending_by_email(identifier):
            raise HTTPException(
                status_code=403,
                detail="Your email is not verified yet. Please check your inbox for the verification email.",
            )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = row[0]
    if not payload.get("success"):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    credential_id = str(payload["credential_id"])
    lead_id       = str(payload["lead_id"])       if payload.get("lead_id")    else None
    account_id    = str(payload["account_id"])    if payload.get("account_id") else None
    contact_id    = str(payload["contact_id"])    if payload.get("contact_id") else None
    first_name    = payload.get("first_name", "")
    last_name     = payload.get("last_name", "")
    source_table  = payload.get("source_table", "leads")

    session_token = _new_session(
        account_id=account_id or "",
        credential_id=credential_id,
        identifier=identifier,
        lead_id=lead_id,
        contact_id=contact_id,
        first_name=first_name,
        last_name=last_name,
        source_table=source_table,
    )

    logger.info(f"Signin OK — lead={lead_id} account={account_id}")
    return AuthResponse(
        success=True,
        message="Signed in successfully",
        session_token=session_token,
        credential_id=credential_id,
        lead_id=lead_id,
        account_id=account_id,
        contact_id=contact_id,
        identifier=identifier,
        email=identifier,
        first_name=first_name,
        last_name=last_name,
        source_table=source_table,
    )


@router.post("/auth/signout", response_model=AuthResponse)
async def signout(req: SignOutRequest):
    """Invalidate a session token."""
    _AUTH_SESSIONS.pop(req.session_token, None)
    return AuthResponse(success=True, message="Signed out")


@router.post("/auth/change-password", response_model=AuthResponse)
async def change_password(req: ChangePasswordRequest):
    """Rotate password (requires the current password for verification)."""
    try:
        if _HASH_ALGO == "argon2id" and _PH and _argon2_exc:
            # Fetch stored hash
            hash_row = _db_fetchone(
                """
                SELECT ac.credential_id, ac.password_hash
                FROM   public.auth_credentials ac
                WHERE  ac.credential_type = 'password'
                  AND  ac.identifier      = lower(%s)
                  AND  ac.is_active       = true
                LIMIT 1
                """,
                (req.identifier,),
            )
            if not hash_row:
                raise HTTPException(status_code=401, detail="Account not found")
            stored_cred_id, stored_hash = hash_row
            try:
                _PH.verify(stored_hash, req.current_password)
            except _argon2_exc.VerifyMismatchError:
                raise HTTPException(status_code=401, detail="Current password is incorrect")

            new_hash = _PH.hash(req.new_password)
            row = _db_fetchone(
                "SELECT public.change_password_prehashed"
                "(%s::text,%s::text,%s::text,%s::text,%s::jsonb) AS ok",
                ("password", req.identifier, stored_hash, new_hash, _ARGON2_PARAMS),
            )
        else:
            row = _db_fetchone(
                "SELECT public.change_password(%s::text,%s::text,%s::text,%s::text) AS ok",
                ("password", req.identifier, req.current_password, req.new_password),
            )
    except HTTPException:
        raise
    except psycopg2.Error as exc:
        logger.error(f"change_password DB error: {exc}")
        raise HTTPException(status_code=500, detail="Password change failed")

    if not row or not row[0]:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect or account not found",
        )
    return AuthResponse(success=True, message="Password changed successfully")


@router.post("/auth/password-reset/request", response_model=AuthResponse)
async def password_reset_request(req: PasswordResetRequestModel):
    """Generate a single-use password reset token.

    Production note: email the returned token to the user; remove
    ``reset_token`` from the response and never log it.
    """
    try:
        row = _db_fetchone(
            "SELECT public.create_password_reset_token(%s::text,%s::text,%s::int) AS token",
            ("password", req.identifier, req.ttl_seconds),
        )
    except psycopg2.Error as exc:
        errmsg = str(exc)
        if "No active credential" in errmsg:
            # Do not reveal whether the account exists
            return AuthResponse(
                success=True,
                message="If that account exists, a reset link has been sent",
            )
        logger.error(f"password_reset_request DB error: {exc}")
        raise HTTPException(status_code=500, detail="Reset request failed")

    if not row or not row[0]:
        return AuthResponse(
            success=True,
            message="If that account exists, a reset link has been sent",
        )

    reset_token = str(row[0])
    logger.info(f"Reset token created for identifier={req.identifier!r} (never log the token itself)")
    return AuthResponse(
        success=True,
        message="Reset token generated. In production this is emailed — never logged.",
        reset_token=reset_token,   # DEMO ONLY — remove in production
    )


@router.post("/auth/password-reset/confirm", response_model=AuthResponse)
async def password_reset_confirm(req: PasswordResetConfirmRequest):
    """Consume a reset token and set a new password."""
    try:
        row = _db_fetchone(
            "SELECT public.consume_password_reset_token(%s::text,%s::text) AS ok",
            (req.token, req.new_password),
        )
    except psycopg2.Error as exc:
        logger.error(f"password_reset_confirm DB error: {exc}")
        raise HTTPException(status_code=500, detail="Password reset failed")

    if not row or not row[0]:
        raise HTTPException(
            status_code=400,
            detail="Invalid, expired, or already-used reset token",
        )
    return AuthResponse(success=True, message="Password reset. Please sign in.")


@router.get("/auth/address")
async def get_address(
    lead_id:    Optional[str] = None,
    contact_id: Optional[str] = None,
    account_id: Optional[str] = None,
    email:      Optional[str] = None,
):
    """Return the shipping address for the given IDs.

    Priority order:
      1. leads.address_line* (inline columns — checked whenever lead_id is supplied)
      2. addresses table via contact_id  (parent_type='contact')
      3. addresses table via account_id  (parent_type='account')
    """
    address = None

    # 1. Leads Table — High Priority (Direct lead_id or conversion links)
    if lead_id:
        try:
            row = _db_fetchone(
                """
                SELECT address_line1, address_line2, city, province, postal_code, country
                FROM   public.leads
                WHERE  lead_id = %s::uuid
                """,
                (lead_id,),
            )
            if row and row[0]: # row[0] is address_line1
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "leads (direct)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address leads direct lookup error: {exc}")

    # 1b. Leads Table — via converted_contact_id
    if not address and contact_id:
        try:
            row = _db_fetchone(
                """
                SELECT address_line1, address_line2, city, province, postal_code, country
                FROM   public.leads
                WHERE  converted_contact_id = %s::uuid
                  AND  address_line1 IS NOT NULL
                ORDER  BY created_at DESC
                LIMIT  1
                """,
                (contact_id,),
            )
            if row and row[0]:
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "leads (via contact conversion)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address leads contact conversion lookup error: {exc}")

    # 1c. Leads Table — via converted_account_id
    if not address and account_id:
        try:
            row = _db_fetchone(
                """
                SELECT address_line1, address_line2, city, province, postal_code, country
                FROM   public.leads
                WHERE  converted_account_id = %s::uuid
                  AND  address_line1 IS NOT NULL
                ORDER  BY created_at DESC
                LIMIT  1
                """,
                (account_id,),
            )
            if row and row[0]:
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "leads (via account conversion)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address leads account conversion lookup error: {exc}")

    # 1d. Leads Table — via email fallback
    if not address and email:
        try:
            row = _db_fetchone(
                """
                SELECT address_line1, address_line2, city, province, postal_code, country
                FROM   public.leads
                WHERE  email = %s
                  AND  address_line1 IS NOT NULL
                ORDER  BY created_at DESC
                LIMIT  1
                """,
                (email,),
            )
            if row and row[0]:
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "leads (via email)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address leads email lookup error: {exc}")

    # 2. Addresses Table — Secondary Priority (Standard addresses)
    if not address and contact_id:
        try:
            row = _db_fetchone(
                """
                SELECT line1, line2, city, province, postal_code, country
                FROM   public.addresses
                WHERE  parent_type = 'contact' AND parent_id = %s::uuid
                ORDER  BY is_default DESC, created_at DESC
                LIMIT  1
                """,
                (contact_id,),
            )
            if row and row[0]:
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "addresses (contact)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address contact addresses lookup error: {exc}")

    if not address and account_id:
        try:
            row = _db_fetchone(
                """
                SELECT line1, line2, city, province, postal_code, country
                FROM   public.addresses
                WHERE  parent_type = 'account' AND parent_id = %s::uuid
                ORDER  BY is_default DESC, created_at DESC
                LIMIT  1
                """,
                (account_id,),
            )
            if row and row[0]:
                address = {
                    "line1": row[0], "line2": row[1], "city": row[2],
                    "province": row[3], "postal_code": row[4], "country": row[5],
                    "source": "addresses (account)",
                }
        except psycopg2.Error as exc:
            logger.warning(f"get_address account addresses lookup error: {exc}")

    return {"success": True, "address": address}


@router.post("/auth/verify-email", response_model=AuthResponse)
async def verify_email(req: VerifyEmailRequest):
    """Mark a contact's email as verified using the token from contacts table."""
    try:
        row = _db_fetchone(
            "SELECT public.verify_email_token(%s::uuid,%s::text) AS ok",
            (req.contact_id, req.token),
        )
    except psycopg2.Error as exc:
        logger.error(f"verify_email DB error: {exc}")
        raise HTTPException(status_code=500, detail="Email verification failed")

    if not row or not row[0]:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired email verification token",
        )
    return AuthResponse(success=True, message="Email verified successfully")
