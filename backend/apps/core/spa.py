"""Serves the React single-page app from the backend (one Render service for API, WebSockets and website).

Static build files (hashed JS/CSS, logos) are served by WhiteNoise from SPA_DIR. `index.html` is NOT served by WhiteNoise: this view
returns it for every page URL and injects runtime settings as <meta> tags (no inline script, so the Content-Security-Policy stays strict).
"""
import logging
import re
from html import escape

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import seo_meta

log = logging.getLogger(__name__)
_cache = {"mtime": None, "html": ""}
PLACEHOLDER = "<!--runtime-config-->"
ROOT = '<div id="root"></div>'
_TITLE = re.compile(r"<title>.*?</title>", re.S)
_DEFAULT_META = re.compile(r'\s*<meta (?:name="description"|property="og:image")[^>]*>')  # replaced per page


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


def render_page(request, html: str, path: str) -> str:
    """index.html with the runtime settings and this page's own title and search / social metadata."""
    try:
        meta = seo_meta.page_meta(request, path)
    except Exception:  # noqa: BLE001 - metadata must never take the website down
        log.exception("could not build page metadata")
        meta = None
    html = _DEFAULT_META.sub("", html)
    if meta:
        html = _TITLE.sub(lambda _: f"<title>{escape(meta['title'])}</title>", html, count=1)
        html = html.replace(ROOT, ROOT + seo_meta.noscript(meta), 1)
    return html.replace(PLACEHOLDER, f"{runtime_meta()}\n    {seo_meta.head_tags(meta)}")


@csrf_exempt  # this view changes nothing; see below
def spa(request, path=""):
    if request.method == "POST":
        # A payment provider may return the customer with a POST. Redirect to the same page with GET; nothing is read from the body.
        # The leading slashes are collapsed so the target can only ever be a path on this site.
        return HttpResponseRedirect("/" + request.get_full_path().lstrip("/"), status=303)
    html = _index_html()
    if html is None:
        return JsonResponse({"success": False, "error": {"code": "frontend_not_built", "message": "The website files are not installed on this server."}}, status=404)
    resp = HttpResponse(render_page(request, html, path), content_type="text/html; charset=utf-8")
    resp["Cache-Control"] = "no-cache"  # always revalidate: a new deploy changes the hashed asset names inside it
    return resp
