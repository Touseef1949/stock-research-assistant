"""
Streamlit payment and Supabase Auth layer for Stock Research Assistant.

Production mode:
    - Supabase Auth email OTP verifies the user's email address.
    - A custom public.users table tracks plan and analysis usage.
    - Service role key performs server-side user/usage updates.

Development mode:
    - If Supabase secrets are missing or invalid, the app falls back to a
      session-only mock user and keeps _session_report_count usage tracking.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import streamlit as st
from supabase import Client, create_client


APP_NAME = "Stock Research Assistant"
AUTH_FILE = Path.home() / ".hermes" / "data" / "sra_auth.json"

FREE_REPORT_LIMIT = 5
REQUIRE_AUTH = False  # Feature flag: True = require email OTP. False = open beta.
PRO_REPORT_LIMIT = 100
INTERNAL_PRO_EMAILS = {"tshaik1990@gmail.com"}

TIER_LIMITS = {
    "free": FREE_REPORT_LIMIT,
    "pro": PRO_REPORT_LIMIT,
}

TIER_PRICES_PAISE = {
    "free": 0,
    "pro": 19_900,
}


def _secret(key: str) -> str:
    """Resolve secret from st.secrets first, then env. Empty string if missing."""
    try:
        val = st.secrets.get(key, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.getenv(key, "").strip()


def _is_placeholder(value: str) -> bool:
    if not value:
        return True
    lowered = value.strip().lower()
    if lowered in {"xxxxx", "...", "eyjhbg...", "rzp_live_...", "your-key", "your-secret"}:
        return True
    # Catch templated secrets like "YOUR_PROJECT_ID", "your-project", etc.
    placeholder_tokens = (
        "xxxxx.supabase.co",
        "your_project_id.supabase.co",
        "your-project.supabase.co",
        "your-project",
        "placeholder",
        "your_project",
    )
    return any(token in lowered for token in placeholder_tokens)


def _valid_supabase_config(key: str) -> bool:
    url = _secret("SUPABASE_URL")
    secret = _secret(key)
    return bool(url and secret and not _is_placeholder(url) and not _is_placeholder(secret))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def save_auth(email: str) -> None:
    """Persist verified email to disk so auth survives page reloads.

    **Production (Supabase configured):** This is intentionally a no-op.
    On shared filesystems like HF Spaces, writing to a single file would
    leak one user's email to every subsequent visitor.  Auth state lives
    exclusively in ``st.session_state`` in production.

    **Local dev (Supabase offline):** Writes to AUTH_FILE so a single
    developer doesn't have to re-enter their email after every page reload.
    """
    if not _supabase_offline():
        return  # Production: session_state is the only auth scope
    clean_email = _normalize_email(email)
    if not clean_email:
        return
    try:
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps({"email": clean_email, "verified_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except Exception:
        return


def load_auth() -> str | None:
    """Load persisted email if auth file exists and is less than 7 days old.

    **Production (Supabase configured):** Always returns ``None``.
    Reading a shared file would auto-authenticate the current visitor as
    whichever user last wrote to it — a critical session-bleed bug on
    multi-user environments like HF Spaces.

    **Local dev (Supabase offline):** Reads AUTH_FILE normally.
    """
    if not _supabase_offline():
        return None  # Production: never read shared file
    try:
        if not AUTH_FILE.is_file():
            return None
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        email = _normalize_email(str(data.get("email", "")))
        verified_raw = str(data.get("verified_at", ""))
        verified_at = datetime.fromisoformat(verified_raw)
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
        now = datetime.now(verified_at.tzinfo)
        if (now - verified_at).total_seconds() >= 7 * 24 * 60 * 60:
            AUTH_FILE.unlink(missing_ok=True)
            return None
        return email if email else None
    except Exception:
        try:
            AUTH_FILE.unlink(missing_ok=True)
        except Exception:
            return None
        return None


def clear_auth() -> None:
    """Delete persisted auth on sign out.

    **Production:** No-op (file was never written).
    **Local dev:** Removes AUTH_FILE.
    """
    if not _supabase_offline():
        return  # Production: no file to clear
    try:
        AUTH_FILE.unlink(missing_ok=True)
    except Exception:
        return


def _is_internal_pro_email(email: str) -> bool:
    return _normalize_email(email) in INTERNAL_PRO_EMAILS


def _internal_pro_payload(email: str, analyses_used: int = 0) -> dict[str, Any]:
    clean_email = _normalize_email(email)
    return {
        "id": None,
        "email": clean_email,
        "plan": "pro",
        "analyses_used": analyses_used,
        "analyses_limit": TIER_LIMITS["pro"],
        "created_at": None,
        "authenticated": True,
        "internal_pro": True,
    }


def _user_payload(row: dict[str, Any]) -> dict[str, Any]:
    email = _normalize_email(str(row.get("email", "")))
    is_internal_pro = _is_internal_pro_email(email)
    plan = "pro" if is_internal_pro else row.get("plan", "free")
    return {
        "id": row.get("id"),
        "email": email,
        "plan": plan,
        "analyses_used": row.get("analyses_used", 0),
        "analyses_limit": TIER_LIMITS.get(str(plan), TIER_LIMITS["free"]),
        "created_at": row.get("created_at"),
        "authenticated": True,
        "internal_pro": is_internal_pro,
    }


@st.cache_resource
def get_supabase_admin():
    """Supabase client for server-side user and usage operations.
    Uses SUPABASE_KEY (anon key) — same as BA Assistant setup.
    For production with RLS, add SUPABASE_SERVICE_KEY and swap this."""
    if not _valid_supabase_config("SUPABASE_KEY"):
        return None
    try:
        client: Client = create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_KEY"))
        return client
    except Exception:
        return None


@st.cache_resource
def get_supabase_client():
    """Anon Supabase client for Auth email OTP operations."""
    if not _valid_supabase_config("SUPABASE_KEY"):
        return None
    try:
        client: Client = create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_KEY"))
        return client
    except Exception:
        return None


@st.cache_resource
def get_supabase():
    """Backward-compatible service-role Supabase client."""
    return get_supabase_admin()


class _MockUser:
    """Returned when Supabase is not configured; keeps local dev usable."""

    plan = "free"
    analyses_used = 0
    analyses_limit = TIER_LIMITS["free"]
    email = "mock@local"
    created_at = None
    authenticated = False


def _supabase_offline() -> bool:
    return get_supabase_admin() is None


def get_user(email: str):
    """
    Fetch the custom users row for a verified email.

    Returns a dict in production, None when no row exists, or _MockUser when Supabase is unavailable.
    """
    clean_email = _normalize_email(email)
    sb = get_supabase_admin()
    if not clean_email:
        return _MockUser()
    if sb is None:
        if _is_internal_pro_email(clean_email):
            return _internal_pro_payload(clean_email, st.session_state.get("_session_report_count", 0))
        return _MockUser()

    try:
        res = sb.table("users").select("*").eq("email", clean_email).limit(1).execute()
        if res.data:
            return _user_payload(res.data[0])

        return None
    except Exception:
        return _MockUser()


def send_otp(email: str) -> bool:
    """Send a Supabase Auth email OTP."""
    clean_email = _normalize_email(email)
    client = get_supabase_client()
    if client is None or not clean_email:
        return False
    try:
        auth = client.auth
        if hasattr(auth, "sign_in_with_otp"):
            auth.sign_in_with_otp({"email": clean_email})
        else:
            auth.signInWithOtp({"email": clean_email})
        return True
    except Exception:
        return False


def _read_attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _auth_user_id(auth_response: Any) -> Optional[str]:
    user = _read_attr(auth_response, "user")
    if user is None:
        session = _read_attr(auth_response, "session")
        user = _read_attr(session, "user")
    return _read_attr(user, "id")


def _ensure_user_row(email: str, auth_user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Create or refresh the public.users row after Supabase Auth verifies the email."""
    clean_email = _normalize_email(email)
    sb = get_supabase_admin()
    if sb is None or not clean_email:
        return None

    now = _now_iso()
    existing = get_user(clean_email)
    if isinstance(existing, dict):
        # Only update columns that exist in the users table.
        updates: dict[str, Any] = {}
        if _is_internal_pro_email(clean_email):
            updates["plan"] = "pro"
            updates["analyses_limit"] = TIER_LIMITS["pro"]
        if updates:
            try:
                sb.table("users").update(updates).eq("email", clean_email).execute()
                return {**existing, **updates}
            except Exception:
                return existing
        return existing
    if existing is not None:
        return None

    row_plan = "pro" if _is_internal_pro_email(clean_email) else "free"
    row = {
        "email": clean_email,
        "plan": row_plan,
        "analyses_used": 0,
        "analyses_limit": TIER_LIMITS[row_plan],
        "created_at": now,
    }
    # NOTE: id is BIGSERIAL auto-increment — do NOT set it to the
    # Supabase Auth UUID (which is a different type and will fail).
    # Also: confirmed_at / last_login_at columns do NOT exist in the
    # users table — keep inserts to the columns that actually exist.
    try:
        created = sb.table("users").insert(row).execute()
        if created.data:
            return _user_payload(created.data[0])
        return _user_payload(row)
    except Exception:
        return None


def verify_otp(email: str, token: str) -> Optional[Any]:
    """Verify a Supabase Auth email OTP."""
    clean_email = _normalize_email(email)
    clean_token = (token or "").strip()
    client = get_supabase_client()
    if client is None or not clean_email or not clean_token:
        return None
    try:
        payload = {"email": clean_email, "token": clean_token, "type": "email"}
        auth = client.auth
        if hasattr(auth, "verify_otp"):
            return auth.verify_otp(payload)
        else:
            return auth.verifyOtp(payload)
    except Exception:
        return None


def is_authenticated() -> bool:
    return bool(st.session_state.get("_auth_verified", False))


def require_payment(email: str) -> bool:
    """
    Call before running an analysis.
    Returns True if the authenticated user is allowed to proceed.
    """
    if not REQUIRE_AUTH:
        st.info("Free during beta")
        return True

    clean_email = _normalize_email(email)
    if not clean_email:
        st.warning("Enter your email in the sidebar to start.")
        return False

    if not is_authenticated():
        st.warning("Verify your email first.")
        return False

    user = get_user(clean_email)
    if user is None:
        st.warning("Verify your email in the sidebar before generating reports.")
        return False

    is_mock = not isinstance(user, dict)
    used = user.get("analyses_used", 0) if not is_mock else user.analyses_used
    limit = user.get("analyses_limit", TIER_LIMITS["free"]) if not is_mock else user.analyses_limit
    plan = user.get("plan", "free") if not is_mock else user.plan

    claimed_email = st.session_state.get("_free_account_claimed_email")
    if plan == "free" and st.session_state.get("_free_account_claimed") and clean_email != claimed_email:
        st.warning(
            "Free tier is limited to one account per session. "
            "Use your existing email or upgrade to Pro."
        )
        return False

    if is_mock:
        used = st.session_state.get("_session_report_count", 0)
        limit = TIER_LIMITS["free"]

    if plan == "free" and not st.session_state.get("_free_account_claimed"):
        st.session_state["_free_account_claimed"] = True
        st.session_state["_free_account_claimed_email"] = clean_email

    if used >= limit:
        _render_upgrade_ui(clean_email, plan)
        return False

    remaining = max(0, limit - used)
    st.info(f"{str(plan).upper()} plan · {remaining} reports remaining.")
    return True


def track_usage(email: str, feature: str = "default") -> None:
    """Track a successful analysis in session state and Supabase when available."""
    current = st.session_state.get("_session_report_count", 0)
    st.session_state["_session_report_count"] = current + 1

    clean_email = _normalize_email(email)
    sb = get_supabase_admin()
    if sb is None or not clean_email:
        return

    try:
        res = sb.table("users").select("analyses_used").eq("email", clean_email).limit(1).execute()
        used = 0
        if res.data:
            used = int(res.data[0].get("analyses_used") or 0)
        sb.table("users").update({"analyses_used": used + 1}).eq("email", clean_email).execute()
    except Exception:
        pass


def _create_payment_link(email: str, plan: str) -> Optional[str]:
    """Create Razorpay payment link and return short_url, or None on failure."""
    key_id = _secret("RAZORPAY_KEY_ID")
    key_secret = _secret("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret or _is_placeholder(key_id) or _is_placeholder(key_secret) or plan == "free":
        return None
    try:
        payload = {
            "amount": TIER_PRICES_PAISE.get(plan, TIER_PRICES_PAISE["pro"]),
            "currency": "INR",
            "accept_partial": False,
            "description": f"{APP_NAME} - {plan.upper()} Plan",
            "customer": {"email": email},
            "notify": {"email": True, "sms": False},
            "notes": {"plan": plan, "email": email, "app": APP_NAME},
        }
        resp = requests.post(
            "https://api.razorpay.com/v1/payment_links",
            auth=(key_id, key_secret),
            json=payload,
            timeout=15,
        )
        return resp.json().get("short_url")
    except Exception:
        return None


def _render_upgrade_ui(email: str, current_plan: str) -> None:
    """Show upgrade buttons for paid tiers."""
    st.warning("Free report limit reached. Upgrade to continue generating research reports.")
    st.caption(f"Current plan: {current_plan.upper()} · Account: {email}")

    paid_plans = [p for p in TIER_PRICES_PAISE if TIER_PRICES_PAISE[p] > 0]
    cols = st.columns(len(paid_plans))
    for idx, plan in enumerate(paid_plans):
        paise = TIER_PRICES_PAISE[plan]
        rupees = paise // 100
        with cols[idx]:
            with st.container(border=True):
                st.subheader(plan.upper())
                st.write(f"₹{rupees}/month")
                st.caption("Unlock higher report limits for continued research.")
                if st.button(f"Upgrade to {plan.upper()}", key=f"up_{plan}"):
                    url = _create_payment_link(email, plan)
                    if url:
                        st.markdown(
                            f"[Open secure payment link]({url}) - after payment, paste your "
                            f"Payment ID below to activate."
                        )
                        payment_id = st.text_input("Razorpay Payment ID", key=f"pid_{plan}")
                        if payment_id and st.button("Activate plan", key=f"act_{plan}"):
                            _activate_plan(email, payment_id, plan)
                    else:
                        st.error("Payment link unavailable. Set Razorpay keys in secrets.")


def _activate_plan(email: str, payment_id: str, plan: str) -> None:
    """Verify payment with Razorpay and update the users table.

    Validates that the payment:
    - Exists and is in 'captured' state
    - Has the correct amount for the selected plan
    - Belongs to the user's email address
    - Was created for this application
    """
    key_id = _secret("RAZORPAY_KEY_ID")
    key_secret = _secret("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret or _is_placeholder(key_id) or _is_placeholder(key_secret):
        st.error("Razorpay keys not configured.")
        return
    try:
        resp = requests.get(
            f"https://api.razorpay.com/v1/payments/{payment_id}",
            auth=(key_id, key_secret),
            timeout=10,
        )
        if resp.status_code != 200:
            st.error("Payment not found. Check your Payment ID and try again.")
            return

        payment = resp.json()
        if payment.get("status") != "captured":
            st.error("Payment not captured yet. Try again in a moment.")
            return

        # ── Validate payment details match the plan ──
        expected_amount = TIER_PRICES_PAISE.get(plan)
        if expected_amount is None:
            st.error(f"Unknown plan: {plan}")
            return

        actual_amount = int(payment.get("amount", 0))
        if actual_amount != expected_amount:
            st.error(
                f"Payment amount (₹{actual_amount // 100}) does not match "
                f"the {plan.upper()} plan price (₹{expected_amount // 100})."
            )
            return

        # ── Validate email match ──
        payment_email = (payment.get("email", "") or "").strip().lower()
        if payment_email and payment_email != _normalize_email(email):
            st.error(
                "This payment is linked to a different email address. "
                "Please use the email associated with the payment."
            )
            return

        # ── Validate app notes ──
        notes = payment.get("notes", {}) or {}
        if notes.get("app") != APP_NAME:
            st.error(
                "This payment was not created for Stock Research Assistant. "
                "Please use a valid upgrade payment ID."
            )
            return

        # ── All checks passed — upgrade the user ──
        sb = get_supabase_admin()
        if sb:
            sb.table("users").update(
                {
                    "plan": plan,
                    "analyses_limit": TIER_LIMITS[plan],
                }
            ).eq("email", _normalize_email(email)).execute()
        st.success(f"{plan.upper()} plan activated. Reload to continue.")
        st.balloons()
    except Exception as exc:
        st.error(f"Verification failed: {exc}")


def _reset_auth_for_email(email: str) -> None:
    st.session_state.user_email = email
    st.session_state["_auth_verified"] = False
    st.session_state["_otp_sent"] = False
    st.session_state["_otp_email"] = ""


def render_email_gate() -> str:
    """
    Render the sidebar email OTP flow.
    Returns the verified email string for the existing app interface.
    """
    if not REQUIRE_AUTH:
        with st.sidebar:
            st.markdown('<div class="sidebar-section-title">Access</div>', unsafe_allow_html=True)
            st.success('Free during beta')
            st.caption('No login required - open access')
        return 'beta-user@sra.local'

    if "user_email" not in st.session_state:
        st.session_state.user_email = ""
    if "_auth_verified" not in st.session_state:
        st.session_state["_auth_verified"] = False
    if "_otp_sent" not in st.session_state:
        st.session_state["_otp_sent"] = False

    if not st.session_state.get("_auth_verified") and not st.session_state.get("user_email"):
        persisted_email = load_auth()
        if persisted_email:
            user = get_user(persisted_email)
            if user:
                st.session_state["_auth_verified"] = True
                st.session_state.user_email = persisted_email

    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">Access</div>', unsafe_allow_html=True)

        verified_email = _normalize_email(st.session_state.user_email)
        if is_authenticated() and verified_email:
            user = get_user(verified_email)
            plan = user.get("plan", "free") if isinstance(user, dict) else getattr(user, "plan", "free")
            used = user.get("analyses_used", 0) if isinstance(user, dict) else st.session_state.get("_session_report_count", 0)
            limit = user.get("analyses_limit", TIER_LIMITS["free"]) if isinstance(user, dict) else TIER_LIMITS["free"]
            st.success(f"✓ Verified as {verified_email}")
            if not REQUIRE_AUTH:
                st.caption("Free during beta")
            elif str(plan).lower() == "free":
                st.caption(f"FREE plan - {used}/{limit} analyses used")
            else:
                st.caption(f"{str(plan).upper()} plan - {used}/{limit} analyses used")
            if st.button("Sign out", key="supabase_sign_out", use_container_width=True):
                st.session_state.user_email = ""
                st.session_state.email_confirmed = False
                for key in ("_auth_verified", "_supabase_session", "_otp_sent", "_otp_email", "_email_input", "_otp_input"):
                    st.session_state.pop(key, None)
                clear_auth()
                client = get_supabase_client()
                if client is not None:
                    try:
                        client.auth.sign_out()
                    except Exception:
                        pass
                st.rerun()
            return verified_email

        email = st.text_input(
            "Email",
            value=st.session_state.get("_otp_email", ""),
            placeholder="you@company.com",
            key="_email_input",
            help="Used to verify access, check your plan, and track report usage.",
        )
        clean_email = _normalize_email(email)

        if clean_email != st.session_state.get("_otp_email", ""):
            st.session_state["_otp_email"] = clean_email
            st.session_state["_otp_sent"] = False
            st.session_state["_auth_verified"] = False
            st.session_state.user_email = ""
            clear_auth()

        if _supabase_offline():
            st.session_state.user_email = clean_email
            st.session_state["_auth_verified"] = bool(clean_email)
            if clean_email:
                save_auth(clean_email)
            st.caption("Dev mode: Supabase Auth is not configured, using session-only access.")
            if clean_email:
                user = get_user(clean_email)
                if isinstance(user, dict):
                    plan = user.get("plan", "free")
                    limit = user.get("analyses_limit", TIER_LIMITS["free"])
                else:
                    plan = getattr(user, "plan", "free")
                    limit = getattr(user, "analyses_limit", TIER_LIMITS["free"])
                used = st.session_state.get("_session_report_count", 0)
                st.success(f"Verified as {clean_email}")
                if not REQUIRE_AUTH:
                    st.caption("Free during beta")
                else:
                    st.caption(f"{str(plan).upper()} plan - {used}/{limit} analyses used")
            return st.session_state.user_email

        if st.button(
            "Send OTP",
            key="send_otp_button",
            use_container_width=True,
            type="secondary",
        ):
            if not clean_email:
                st.warning("Please enter your email address first.")
            elif "@" not in clean_email or "." not in clean_email.split("@")[-1]:
                st.warning("Please enter a valid email address (e.g. you@company.com).")
            elif send_otp(clean_email):
                st.session_state["_otp_sent"] = True
                st.session_state["_otp_email"] = clean_email
                st.success("OTP sent. Check your email.")
            else:
                st.error("Could not send OTP. Check Supabase Auth settings and secrets.")

        if st.session_state.get("_otp_sent") and st.session_state.get("_otp_email") == clean_email:
            token = st.text_input(
                "OTP",
                value="",
                max_chars=8,
                key="_otp_input",
                help="Enter the 6-8 digit code from your email. Copy and paste is supported.",
            )
            if st.button(
                "Verify",
                key="verify_otp_button",
                use_container_width=True,
                type="secondary",
            ):
                auth_response = verify_otp(clean_email, token)
                if auth_response:
                    st.session_state["_supabase_session"] = _read_attr(auth_response, "session")
                    st.session_state["_auth_verified"] = True
                    st.session_state.user_email = clean_email
                    st.session_state["_otp_sent"] = False
                    save_auth(clean_email)
                    _ensure_user_row(clean_email, _auth_user_id(auth_response))
                    st.success(f"✓ Verified as {clean_email}")
                    st.rerun()
                else:
                    st.error("Invalid or expired OTP.")

        st.caption("Email verification is required before running stock analysis.")

    return st.session_state.user_email if is_authenticated() else ""
