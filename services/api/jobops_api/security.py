from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .settings import Settings, load_settings


INTERNAL_API_KEY_HEADER = "X-JobOps-Internal-Key"


def require_internal_api_key(
    provided_key: str | None = Header(default=None, alias=INTERNAL_API_KEY_HEADER),
) -> None:
    try:
        settings = load_settings()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="API security configuration is invalid.") from exc

    validate_internal_api_key(provided_key, settings)


def validate_internal_api_key(provided_key: str | None, settings: Settings) -> None:
    expected_key = (settings.internal_api_key or "").strip()
    is_prod = settings.app_env.lower() == "prod"

    if not expected_key:
        if is_prod:
            raise HTTPException(status_code=503, detail="API security is not configured.")
        return

    if not provided_key:
        raise HTTPException(status_code=401, detail="Internal API key is required.")

    if not hmac.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=403, detail="Internal API key is invalid.")
