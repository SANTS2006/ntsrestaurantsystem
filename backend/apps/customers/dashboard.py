from rest_framework.response import Response

from apps.orders.models import Order, OrderStatusHistory, Status
from apps.orders.serializers import OrderListSerializer
from apps.orders.services import label

from .views import CustomerBase

CURRENT = [Status.AWAITING_PAYMENT, Status.PAYMENT_PROCESSING, Status.CONFIRMED, Status.RECEIVED, Status.PREPARING,
           Status.READY_FOR_PICKUP, Status.OUT_FOR_DELIVERY]


class DashboardView(CustomerBase):
    def get(self, request):
        mine = Order.unscoped.filter(restaurant=request.tenant, customer=request.user)
        recent = mine.select_related("branch").prefetch_related("items")[:5]
        activity = (OrderStatusHistory.unscoped.filter(restaurant=request.tenant, order__customer=request.user)
                    .select_related("order").order_by("-created_at", "-id")[:8])
        paid = mine.filter(amount_paid__gt=0).select_related("branch").prefetch_related("items")[:5]
        return Response({
            "total_orders": mine.count(),
            "current_orders": mine.filter(status__in=CURRENT).count(),
            "completed_orders": mine.filter(status=Status.COMPLETED).count(),
            "cancelled_orders": mine.filter(status=Status.CANCELLED).count(),
            "recent_orders": OrderListSerializer(recent, many=True, context={"request": request}).data,
            "recent_transactions": OrderListSerializer(paid, many=True, context={"request": request}).data,
            "recent_activity": [{"order_id": h.order_id, "order_number": h.order.number, "status": h.to_status,
                                 "status_label": label(h.to_status), "note": h.note, "created_at": h.created_at} for h in activity],
        })
