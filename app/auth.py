"""
Authentication module — API Key + JWT.

API Key: simple header-based auth for service-to-service calls.
JWT: token-based auth for user-facing clients.
"""
import os
import time
import logging
import jwt
from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Verify X-API-Key header against AGENT_API_KEY env var.
    Returns the key on success, raises 401 on failure.
    """
    from app.config import settings

    if not api_key or api_key != settings.agent_api_key:
        logger.warning("Invalid or missing API key attempt")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


# ─────────────────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────────────────

def create_access_token(subject: str, expires_in: int = 3600) -> str:
    """Create a signed JWT token valid for `expires_in` seconds."""
    from app.config import settings

    payload = {
        "sub": subject,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_jwt_token(token: str) -> dict:
    """
    Decode and validate JWT token.
    Raises 401 HTTPException on any failure.
    """
    from app.config import settings

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
