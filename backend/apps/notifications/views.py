from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .details import related_details
from .models import Notification

PAGE_SIZE = 20


def _mine(request):
    """The caller's own notifications for the place they are in (a restaurant, or the platform)."""
    return Notification.objects.filter(user=request.user, restaurant=getattr(request, "tenant", None))


def row(n):
    return {"id": n.pk, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at, "read": n.read_at is not None, "read_at": n.read_at}


class NotificationsView(APIView):
    """`?after=<id>` for the bell (only newer ones); `?page=N&unread=1` for the notifications page."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _mine(request)
        unread = qs.filter(read_at__isnull=True).count()
        after = request.query_params.get("after", "")
        items = qs.filter(pk__gt=int(after)) if after.isdigit() else qs
        if request.query_params.get("unread") == "1":
            items = items.filter(read_at__isnull=True)
        page = request.query_params.get("page", "")
        page = max(1, int(page)) if page.isdigit() else 1
        size = PAGE_SIZE if "page" in request.query_params else 50
        total = items.count()
        chunk = items[(page - 1) * size: page * size]
        return Response({"success": True, "data": {"unread": unread, "count": total, "page": page, "has_next": page * size < total,
                                                   "items": [row(n) for n in chunk]}})


class NotificationDetailView(APIView):
    """One notification with the full record it is about. Opening it marks it read."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        n = _mine(request).filter(pk=pk).first()
        if n is None:
            raise NotFound()
        if n.read_at is None:
            n.read_at = timezone.now()
            n.save(update_fields=["read_at"])
        return Response({"success": True, "data": {**row(n), "details": related_details(request, n)}})


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
