"""Serves the React single-page app from the backend (one Render service for API, WebSockets and website).

Static build files (hashed JS/CSS, logos) are served by WhiteNoise from SPA_DIR. `index.html` is NOT served by WhiteNoise: this view
returns it for every page URL and injects runtime settings as <meta> tags (no inline script, so the Content-Security-Policy stays strict).
"""
import logging
from html import escape

from django.conf import settings
from django.http import HttpResponse, JsonResponse

log = logging.getLogger(__name__)
_cache = {"mtime": None, "html": ""}
PLACEHOLDER = "<!--runtime-config-->"


def _index_html() -> str | None:
    path = settings.SPA_INDEX
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _cache["mtime"] != mtime:
        _cache.update(mtime=mtime, html=path.read_text(encoding="utf-8"))
    return _cache["html"]


def runtime_meta() -> str:
    pairs = {"platform-hosts": ",".join(settings.PLATFORM_HOSTS), "google-client-id": settings.GOOGLE_OAUTH_CLIENT_ID}
    return "\n    ".join(f'<meta name="{k}" content="{escape(v, quote=True)}" />' for k, v in pairs.items())


def spa(request, path=""):
    html = _index_html()
    if html is None:
        return JsonResponse({"success": False, "error": {"code": "frontend_not_built", "message": "The website files are not installed on this server."}}, status=404)
    resp = HttpResponse(html.replace(PLACEHOLDER, runtime_meta()), content_type="text/html; charset=utf-8")
    resp["Cache-Control"] = "no-cache"  # always revalidate: a new deploy changes the hashed asset names inside it
    return resp
