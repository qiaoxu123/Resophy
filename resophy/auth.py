"""
User authentication via Flarum.

Supports two authentication strategies (automatic fallback):
1. Flarum REST API  (preferred, requires FLARUM_API_URL)
2. Direct MySQL bcrypt verification (fallback, requires FLARUM_DB_* creds)

After successful authentication, issues a JWT containing the Flarum user id
and username.  All subsequent API requests carry the JWT in an Authorization
header (Bearer scheme) or in a cookie.
"""

from __future__ import annotations

import datetime
from typing import Optional, Tuple

import jwt
import requests

from resophy.config import AppConfig


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(user_id: int, username: str, cfg: AppConfig) -> str:
    """Create a signed JWT for the authenticated user."""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "username": username,
        "iat": now,
        "exp": now + datetime.timedelta(days=7),
    }
    return jwt.encode(payload, cfg.secret_key, algorithm="HS256")


def verify_token(token: str, cfg: AppConfig) -> Optional[dict]:
    """
    Verify and decode a JWT.

    Returns the payload dict on success, or None on failure.
    """
    try:
        payload = jwt.decode(token, cfg.secret_key, algorithms=["HS256"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ---------------------------------------------------------------------------
# Flarum REST API authentication
# ---------------------------------------------------------------------------

def _auth_via_api(
    identification: str, password: str, cfg: AppConfig
) -> Tuple[bool, Optional[dict], str]:
    """
    Authenticate against Flarum REST API (POST /api/token).

    Returns (success, user_info_dict, error_message).
    """
    api_url = cfg.flarum.api_url
    if not api_url:
        return False, None, "FLARUM_API_URL not configured"

    token_url = f"{api_url.rstrip('/')}/api/token"
    try:
        resp = requests.post(
            token_url,
            json={
                "identification": identification,
                "password": password,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return False, None, f"Flarum API request failed: {e}"

    if resp.status_code != 200:
        return False, None, "Invalid username or password"

    data = resp.json()
    flarum_user_id = data.get("userId")
    if not flarum_user_id:
        return False, None, "Flarum API returned unexpected response"

    # Fetch user details (username, avatar, etc.)
    user_info = _fetch_flarum_user(flarum_user_id, cfg)
    return True, user_info, ""


def _fetch_flarum_user(user_id: int, cfg: AppConfig) -> dict:
    """Fetch user profile from Flarum REST API."""
    api_url = cfg.flarum.api_url
    user_url = f"{api_url.rstrip('/')}/api/users/{user_id}"
    try:
        resp = requests.get(user_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            attrs = data.get("attributes", {})
            return {
                "id": user_id,
                "username": attrs.get("username", ""),
                "display_name": attrs.get("displayName", ""),
                "avatar_url": attrs.get("avatarUrl"),
                "email": attrs.get("email", ""),
            }
    except requests.RequestException:
        pass

    # Minimal fallback
    return {"id": user_id, "username": "", "display_name": "", "avatar_url": None}


# ---------------------------------------------------------------------------
# Direct MySQL bcrypt authentication (fallback)
# ---------------------------------------------------------------------------

def _auth_via_db(
    identification: str, password: str, cfg: AppConfig
) -> Tuple[bool, Optional[dict], str]:
    """
    Authenticate directly against Flarum's MySQL users table.

    Flarum stores bcrypt hashes with the ``$2y$`` prefix.  The ``bcrypt``
    library expects ``$2b$``, so we swap the prefix before checking.
    """
    try:
        from resophy.db import get_flarum_db
    except RuntimeError:
        return False, None, "Flarum database not configured"

    import bcrypt as _bcrypt

    table = cfg.flarum.users_table

    try:
        with get_flarum_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, username, email, password, avatar_url "
                    f"FROM {table} "
                    f"WHERE username = %s OR email = %s "
                    f"LIMIT 1",
                    (identification, identification),
                )
                row = cur.fetchone()
    except Exception as e:
        return False, None, f"Database query failed: {e}"

    if not row:
        return False, None, "Invalid username or password"

    stored_hash: str = row["password"]
    # Flarum uses $2y$, bcrypt lib expects $2b$
    if stored_hash.startswith("$2y$"):
        stored_hash = "$2b$" + stored_hash[4:]

    if not _bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
        return False, None, "Invalid username or password"

    return True, {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["username"],
        "avatar_url": row.get("avatar_url"),
        "email": row.get("email", ""),
    }, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def authenticate(
    identification: str, password: str, cfg: AppConfig
) -> Tuple[bool, Optional[dict], str]:
    """
    Authenticate a user.  Tries Flarum REST API first, then falls back
    to direct MySQL bcrypt verification.

    Returns ``(success, user_info, error_message)``.
    ``user_info`` keys: id, username, display_name, avatar_url, email.
    """
    if cfg.flarum.api_url:
        ok, info, err = _auth_via_api(identification, password, cfg)
        if ok:
            return True, info, ""
        # If API is configured but request failed (network error),
        # fall through to DB.  If credentials are wrong, return immediately.
        if "Invalid username or password" in err:
            return False, None, err

    # Fallback to DB
    return _auth_via_db(identification, password, cfg)
