"""Consistent API error envelope: {"success": false, "error": {"code", "message", "details"}}."""
import logging

from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

log = logging.getLogger(__name__)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        log.exception("Unhandled API exception")  # never echo internals to the client
        return Response({"success": False, "error": {"code": "server_error", "message": "Internal server error."}}, status=500)
    data = response.data
    message = data.get("detail") if isinstance(data, dict) and "detail" in data else "Request failed."
    response.data = {
        "success": False,
        "error": {
            "code": getattr(getattr(exc, "detail", None), "code", None) or getattr(exc, "default_code", "error"),  # a specific code (e.g. mfa_enrollment_required) wins
            "message": str(message),
            "details": None if isinstance(data, dict) and "detail" in data else data,
        },
    }
    return response


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap every successful JSON body as {"success": true, "data": ...} (errors are wrapped by the exception handler)."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        already = isinstance(data, dict) and "success" in data
        if response is not None and response.status_code < 400 and response.status_code != 204 and not already:
            data = {"success": True, "data": data}
        return super().render(data, accepted_media_type, renderer_context)

