from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification


def _mine(request):
    """The caller's own notifications for the place they are in (a restaurant, or the platform)."""
    return Notification.objects.filter(user=request.user, restaurant=getattr(request, "tenant", None))


class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _mine(request)
        after = request.query_params.get("after", "")
        items = qs.filter(pk__gt=int(after)) if after.isdigit() else qs
        rows = [{"id": n.pk, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at, "read": n.read_at is not None}
                for n in items[:50]]
        return Response({"success": True, "data": {"unread": qs.filter(read_at__isnull=True).count(), "items": rows}})


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        qs = _mine(request).filter(read_at__isnull=True)
        ids = request.data.get("ids")
        if isinstance(ids, list):
            qs = qs.filter(pk__in=[i for i in ids if isinstance(i, int)])
        qs.update(read_at=timezone.now())
        return Response({"success": True, "data": {"unread": _mine(request).filter(read_at__isnull=True).count()}})


class ClearView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _mine(request).filter(read_at__isnull=False).delete()
        return Response({"success": True, "data": {}})
