import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.core.models import audit
from apps.orders.pricing import price_cart

from .models import DiningTable, QRMenuRequest
from .realtime import notify_branch


def table_for_token(tenant, token):
    """Public lookup. Unknown, disabled, other-restaurant and suspended-branch all look identical (404)."""
    t = (DiningTable.unscoped.select_related("branch", "restaurant")
         .filter(qr_token=token, restaurant=tenant, is_active=True, branch__status="active").first())
    if t is None:
        raise NotFound("This QR code is not valid.")
    return t


def client_hash(request):
    ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", ""))
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()


def request_json(r):
    return {"id": r.pk, "public_id": str(r.public_id), "status": r.status, "branch_id": r.branch_id, "branch_name": r.branch.name,
            "table_id": r.table_id, "table": r.table.label, "customer_name": r.customer_name, "customer_phone": r.customer_phone,
            "notes": r.notes, "summary": r.summary, "created_at": r.created_at, "order_id": r.order_id, "reject_reason": r.reject_reason}


@transaction.atomic
def submit_request(request, token, data):
    tenant = request.tenant
    table = table_for_token(tenant, token)
    st = tenant.get_settings()
    if not st.qr_guest_orders_allowed:
        raise PermissionDenied("Table ordering by QR is not available. Please ask a member of staff.")
    if st.qr_identification in ("name", "phone") and not data["customer_name"].strip():
        raise serializers.ValidationError({"customer_name": "Please enter your name."})
    if st.qr_identification == "phone" and not data["customer_phone"].strip():
        raise serializers.ValidationError({"customer_phone": "Please enter your phone number."})
    pending = QRMenuRequest.unscoped.filter(table=table, status="new").count()
    if pending >= settings.QR_MAX_PENDING_PER_TABLE:
        raise serializers.ValidationError({"detail": "This table already has several requests waiting. Please ask a member of staff."})
    quote = price_cart(tenant, data["items"], "dine_in")  # validates availability, options and stock; amounts are ours
    q = quote.as_dict()
    summary = {"lines": [{"name": l["name"], "variation": l["variation"], "quantity": l["quantity"], "addons": [f'{a["quantity"]}x {a["name"]}' for a in l["addons"]],
                          "instructions": l["instructions"], "line_total": l["line_total"]} for l in q["lines"]],
               "total": q["total"], "currency": q["currency"]}
    req = QRMenuRequest.objects.create(restaurant=tenant, branch=table.branch, table=table, items=data["items"], summary=summary,
                                       customer_name=data["customer_name"].strip(), customer_phone=data["customer_phone"].strip(),
                                       notes=data["notes"].strip(), client_hash=client_hash(request))
    audit("qr.request_created", restaurant=tenant, obj=req, metadata={"table": table.label}, request=request)
    notify_branch(tenant.pk, table.branch_id, {"type": "qr.request.created", "id": req.pk, "table": table.label, "branch_id": table.branch_id,
                                                 "branch": table.branch.name, "lines": len(summary["lines"]), "total": summary["total"],
                                                 "currency": summary["currency"], "created_at": req.created_at.isoformat()})
    from apps.notifications import inapp

    inapp.notify_staff(tenant, table.branch_id, inapp.FRONT_OF_HOUSE, "request", f"Table {table.label} sent an order request", f"{summary['currency']} {summary['total']}", "/manage/cashier", about=("qr_request", req.pk))
    return req


@transaction.atomic
def reject_request(request, request_id, reason, branch_ids):
    r = (QRMenuRequest.unscoped.select_for_update(of=("self",)).select_related("branch", "table")
         .filter(pk=request_id, restaurant=request.tenant, branch_id__in=branch_ids).first())
    if r is None:
        raise NotFound()
    if r.status != QRMenuRequest.Status.NEW:
        raise serializers.ValidationError({"detail": "This request was already handled."})
    r.status, r.handled_by, r.handled_at, r.reject_reason = QRMenuRequest.Status.REJECTED, request.user, timezone.now(), reason[:200]
    r.save()
    audit("qr.request_rejected", actor=request.user, restaurant=request.tenant, obj=r, metadata={"reason": reason[:200]}, request=request)
    notify_branch(request.tenant.pk, r.branch_id, {"type": "qr.request.updated", "id": r.pk, "status": r.status})
    return r
