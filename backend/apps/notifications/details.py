"""The record a notification is about, as label/value pairs. Visibility is checked again NOW: a person who no longer may see the
record (moved branch, changed role) gets no details, only the notification text they already received."""


def _fields(*pairs):
    return [{"label": k, "value": str(v)} for k, v in pairs if v not in (None, "")]


def _may_see_branch(request, branch_id):
    from apps.accounts.permissions import accessible_branch_ids

    return branch_id in accessible_branch_ids(request)


def _when(value):
    return value.strftime("%d %b %Y, %H:%M") if value else ""


def related_details(request, n):
    tenant = getattr(request, "tenant", None)
    if tenant is None or not n.object_id:
        return None
    if n.object_type == "order":
        from apps.orders.models import Order

        o = Order.unscoped.filter(pk=n.object_id, restaurant=tenant).select_related("branch").prefetch_related("items").first()
        if o is None or not (o.customer_id == request.user.pk or _may_see_branch(request, o.branch_id)):
            return None
        return {"heading": f"Order {o.number}", "fields": _fields(
            ("Status now", o.get_status_display()), ("Payment", f"{o.get_payment_status_display()} ({o.get_payment_method_display()})"),
            ("Total", f"{o.currency} {o.total}"), ("Type", o.get_fulfilment_display()), ("Table", o.table_label), ("Branch", o.branch.name),
            ("Customer", o.contact_name), ("Phone", o.contact_phone), ("Placed", _when(o.created_at)), ("Notes", o.customer_notes)),
            "items": [f"{i.quantity} x {i.product_name}" + (f" ({i.variation_name})" if i.variation_name else "") for i in o.items.all()]}
    if n.object_type == "reservation":
        from apps.floor.models import Reservation

        r = Reservation.unscoped.filter(pk=n.object_id, restaurant=tenant).select_related("branch", "table").first()
        if r is None or not _may_see_branch(request, r.branch_id):
            return None
        return {"heading": f"Reservation {r.reference}", "fields": _fields(
            ("Status now", r.get_status_display()), ("Guest", r.customer_name), ("Phone", r.customer_phone), ("Party", r.party_size),
            ("When", _when(r.starts_at)), ("Table", r.table.label if r.table else ""), ("Branch", r.branch.name), ("Notes", r.notes)), "items": []}
    if n.object_type == "qr_request":
        from apps.qrmenu.models import QRMenuRequest

        q = QRMenuRequest.unscoped.filter(pk=n.object_id, restaurant=tenant).select_related("branch", "table").first()
        if q is None or not _may_see_branch(request, q.branch_id):
            return None
        return {"heading": f"Request from {q.table.label}", "fields": _fields(
            ("Status now", q.get_status_display()), ("Estimated total", f"{q.summary.get('currency', '')} {q.summary.get('total', '')}"),
            ("Guest", q.customer_name), ("Phone", q.customer_phone), ("Branch", q.branch.name), ("Sent", _when(q.created_at)), ("Notes", q.notes)),
            "items": [f"{line.get('quantity')} x {line.get('name')}" for line in q.summary.get("lines", [])]}
    if n.object_type == "catering":
        from apps.catering.models import CateringRequest

        c = CateringRequest.objects.filter(pk=n.object_id, restaurant=tenant).select_related("branch").first()
        if c is None or not (c.branch_id and _may_see_branch(request, c.branch_id)):
            return None
        return {"heading": f"Catering request {c.reference}", "fields": _fields(
            ("Status now", c.get_status_display()), ("Event", c.get_event_type_display()), ("Date", c.event_date), ("Guests", c.guests),
            ("Customer", c.customer_name), ("Branch", c.branch.name)), "items": []}
    return None
