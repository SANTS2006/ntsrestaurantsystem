from rest_framework import serializers

from .models import Fulfilment, Order, OrderItem, OrderStatusHistory, PaymentMethod
from .pricing import LineInput
from .services import allowed_targets, label


class CheckoutAddress(serializers.Serializer):
    recipient_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    delivery_notes = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")


class QuoteSerializer(serializers.Serializer):
    items = LineInput(many=True)
    fulfilment = serializers.ChoiceField(choices=[Fulfilment.DELIVERY, Fulfilment.PICKUP], default=Fulfilment.PICKUP)


class CheckoutSerializer(QuoteSerializer):
    branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.values)
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    contact_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", error_messages={"invalid": "Enter a valid phone number."})
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    address = CheckoutAddress(required=False, allow_null=True, default=None)


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product_name", "variation_name", "unit_price", "quantity", "line_total", "addons", "instructions"]


class HistorySerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="to_status")
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = OrderStatusHistory
        fields = ["status", "status_label", "actor_role", "note", "created_at"]

    def get_status_label(self, h):
        return label(h.to_status)


class OrderListSerializer(serializers.ModelSerializer):
    status_label = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "number", "status", "status_label", "fulfilment", "payment_method", "payment_status", "total", "currency",
                  "item_count", "branch_name", "cancellation_requested", "contact_name", "created_at"]

    def get_status_label(self, o):
        return label(o.status)

    def get_item_count(self, o):
        return sum(i.quantity for i in o.items.all())


class OrderDetailSerializer(OrderListSerializer):
    items = ItemSerializer(many=True, read_only=True)
    history = HistorySerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()
    can_request_cancel = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    def get_payments(self, o):
        return [{"id": p.pk, "method": p.method, "status": p.status, "amount": str(p.amount), "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                 "receipt_id": p.receipt.pk if hasattr(p, "receipt") else None,
                 "checkout_url": p.checkout_url if p.status == "pending" else "",
                 "ussd_code": p.ussd_code if p.status == "pending" else ""} for p in o.payments.all()]

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            "contact_phone", "contact_email", "delivery_address", "customer_notes", "subtotal", "discount_total", "tax_total",
            "tax_rate_percent", "delivery_fee", "amount_paid", "items", "history", "can_cancel", "can_request_cancel",
            "cancellation_reason", "payments"]

    def get_can_cancel(self, o):
        return o.status == "awaiting_payment"

    def get_can_request_cancel(self, o):
        return o.status in ("confirmed", "received") and not o.cancellation_requested


class KitchenOrderSerializer(OrderListSerializer):
    """List row plus what a kitchen board needs, so it never has to fetch one detail per order."""

    items = ItemSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + ["items", "customer_notes", "table_label", "allowed_transitions"]

    def get_allowed_transitions(self, o):
        return [{"status": s, "label": label(s)} for s in allowed_targets(o, self.context["role"])]


class StaffOrderDetailSerializer(OrderDetailSerializer):
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(OrderDetailSerializer.Meta):
        fields = OrderDetailSerializer.Meta.fields + ["allowed_transitions"]

    def get_allowed_transitions(self, o):
        return [{"status": s, "label": label(s)} for s in allowed_targets(o, self.context["role"])]


class TransitionSerializer(serializers.Serializer):
    status = serializers.CharField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
