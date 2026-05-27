from __future__ import annotations

from urllib.parse import urlparse

from jobops_api.settings import Settings


class PublicBaseUrlError(ValueError):
    pass


def resolve_public_app_base_url(settings: Settings, explicit_base_url: str | None = None) -> str:
    base_url = (explicit_base_url or settings.app_base_url or "").strip().rstrip("/")
    if not base_url:
        raise PublicBaseUrlError("JOBOPS_APP_BASE_URL is required to generate account email links.")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicBaseUrlError("JOBOPS_APP_BASE_URL must be an absolute http(s) URL.")

    if settings.app_env.lower() in {"prod", "production"}:
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme != "https":
            raise PublicBaseUrlError("JOBOPS_APP_BASE_URL must use https in production.")
        if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
            raise PublicBaseUrlError("JOBOPS_APP_BASE_URL cannot point to a local host in production.")

    return base_url
