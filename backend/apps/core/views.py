from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def liveness(request):
    return JsonResponse({"status": "ok"})


def readiness(request):
    checks = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "fail"
    try:
        cache.set("readyz", "1", 5)
        checks["cache"] = "ok" if cache.get("readyz") == "1" else "fail"
    except Exception:
        checks["cache"] = "fail"
    ok = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ready" if ok else "degraded", "checks": checks}, status=200 if ok else 503)


def not_found(request, exception=None):
    """JSON 404 for every URL that is neither the API, a file nor a page of the website."""
    return JsonResponse({"success": False, "error": {"code": "not_found", "message": "Not found."}}, status=404)
