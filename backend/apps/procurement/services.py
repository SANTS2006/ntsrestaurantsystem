"""Ingredient stock, recipes and purchase orders. Every stock change writes an append-only movement in the same transaction."""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.accounts.permissions import accessible_branch_ids
from apps.core.models import audit, next_document_number
from apps.tenants.models import Branch

from .models import Ingredient, IngredientMovement, IngredientStock, PurchaseOrder, PurchaseOrderLine, RecipeLine, Supplier

Q3 = Decimal("0.001")
CENT = Decimal("0.01")
R = IngredientMovement.Reason


def q3(x):
    return Decimal(x).quantize(Q3, rounding=ROUND_HALF_UP)


def cents(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def _fail(msg, field="detail"):
    raise serializers.ValidationError({field: msg})


def locked_stock(restaurant, ingredient, branch):
    """The stock row for (ingredient, branch), created on first use and row-locked for the transaction."""
    IngredientStock.unscoped.get_or_create(restaurant=restaurant, ingredient=ingredient, branch=branch)
    return IngredientStock.unscoped.select_for_update().get(ingredient=ingredient, branch=branch)


def move(restaurant, ingredient, branch, delta, reason, actor=None, note="", po=None):
    st = locked_stock(restaurant, ingredient, branch)
    st.quantity = q3(st.quantity + Decimal(delta))
    st.save(update_fields=["quantity", "updated_at"])
    IngredientMovement.objects.create(restaurant=restaurant, branch=branch, ingredient=ingredient, delta=q3(delta), quantity_after=st.quantity,
                                      reason=reason, note=note[:200], actor=actor, purchase_order=po)
    return st


# ---- recipes: called by the order module inside its own transaction -------------------------------------
def _usage(order):
    use: dict[int, Decimal] = defaultdict(Decimal)
    items = list(order.items.all())
    pids = [i.product_id for i in items if i.product_id]
    if not pids:
        return {}
    lines = defaultdict(list)
    for rl in RecipeLine.unscoped.filter(product_id__in=pids).select_related("ingredient"):
        lines[rl.product_id].append(rl)
    for it in items:
        for rl in lines.get(it.product_id, []):
            use[rl.ingredient_id] += rl.quantity * it.quantity
    return use


def apply_recipe_usage(order, actor, *, restore=False):
    """Deduct (or give back) the ingredients used by an order's items at the order's branch. Never blocks a sale."""
    use = _usage(order)
    if not use:
        return
    ings = {i.pk: i for i in Ingredient.unscoped.filter(pk__in=use.keys())}
    for iid in sorted(use):  # fixed order avoids deadlocks between concurrent orders
        move(order.restaurant, ings[iid], order.branch, use[iid] if restore else -use[iid], R.SALE_RETURN if restore else R.SALE, actor, order.number)


# ---- stock adjustments --------------------------------------------------------------------------------------
def branch_for(request, branch_id):
    allowed = accessible_branch_ids(request)
    if branch_id not in allowed:
        raise NotFound()
    return Branch.unscoped.get(pk=branch_id, restaurant=request.tenant)


@transaction.atomic
def adjust(request, ingredient_id, branch_id, mode, quantity, reason, note):
    """mode 'delta' changes by quantity; mode 'set' sets the counted quantity. Reason and note are mandatory (audit trail)."""
    ing = Ingredient.unscoped.filter(pk=ingredient_id, restaurant=request.tenant).first()
    if ing is None:
        raise NotFound()
    branch = branch_for(request, branch_id)
    if reason not in (R.WASTE, R.ADJUSTMENT, R.OPENING):
        _fail("Choose waste, adjustment or opening stock.", "reason")
    if len(note.strip()) < 3:
        _fail("Explain the change.", "note")
    st = locked_stock(request.tenant, ing, branch)
    delta = Decimal(quantity) - st.quantity if mode == "set" else Decimal(quantity)
    if reason == R.WASTE and delta > 0:
        _fail("Waste must reduce stock.", "quantity")
    if delta == 0:
        _fail("That does not change the stock.", "quantity")
    st = move(request.tenant, ing, branch, delta, reason, request.user, note.strip())
    audit("stock.ingredient_adjusted", actor=request.user, restaurant=request.tenant, obj=ing, metadata={"branch": branch.pk, "delta": str(q3(delta)), "reason": reason}, request=request)
    return st


# ---- purchase orders -----------------------------------------------------------------------------------------
def _lines(request, data):
    if not data:
        _fail("Add at least one line.", "lines")
    if len(data) > 100:
        _fail("At most 100 lines.", "lines")
    ids = {d["ingredient_id"] for d in data}
    found = {i.pk: i for i in Ingredient.unscoped.filter(restaurant=request.tenant, pk__in=ids, is_active=True)}
    if len(found) != len(ids):
        _fail("An ingredient is unknown or inactive.", "lines")
    return [(found[d["ingredient_id"]], q3(d["quantity"]), Decimal(d["unit_cost"]).quantize(Decimal("0.0001"))) for d in data]


def _supplier(request, sid):
    s = Supplier.unscoped.filter(pk=sid, restaurant=request.tenant, is_active=True).first()
    if s is None:
        _fail("Choose an active supplier.", "supplier_id")
    return s


@transaction.atomic
def create_po(request, data):
    branch = branch_for(request, data["branch_id"])
    supplier = _supplier(request, data["supplier_id"])
    lines = _lines(request, data["lines"])
    po = PurchaseOrder.objects.create(restaurant=request.tenant, branch=branch, supplier=supplier, number=next_document_number(request.tenant, "po", "PO"),
                                      expected_date=data.get("expected_date"), notes=data.get("notes", ""), currency=request.tenant.get_settings().currency, created_by=request.user)
    _set_lines(po, lines)
    audit("po.created", actor=request.user, restaurant=request.tenant, obj=po, metadata={"number": po.number, "total": str(po.total)}, request=request)
    return po


def _set_lines(po, lines):
    PurchaseOrderLine.unscoped.filter(order=po).delete()
    total = Decimal("0")
    for ing, qty, cost in lines:
        PurchaseOrderLine.objects.create(restaurant=po.restaurant, order=po, ingredient=ing, quantity=qty, unit_cost=cost)
        total += cents(qty * cost)
    po.total = total
    po.save(update_fields=["total", "updated_at"])


def _po(request, pk, lock=True):
    qs = PurchaseOrder.unscoped.filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request))
    po = (qs.select_for_update() if lock else qs).first()
    if po is None:
        raise NotFound()
    return po


@transaction.atomic
def update_po(request, pk, data):
    po = _po(request, pk)
    if po.status != PurchaseOrder.Status.DRAFT:
        _fail("Only a draft purchase order can be edited.")
    if "supplier_id" in data:
        po.supplier = _supplier(request, data["supplier_id"])
    for f in ("expected_date", "notes"):
        if f in data:
            setattr(po, f, data[f])
    po.save()
    if "lines" in data:
        _set_lines(po, _lines(request, data["lines"]))
    return po


@transaction.atomic
def place_po(request, pk):
    po = _po(request, pk)
    if po.status != PurchaseOrder.Status.DRAFT:
        _fail("Only a draft can be placed.")
    if not po.lines.exists():
        _fail("Add at least one line.")
    po.status, po.ordered_at = PurchaseOrder.Status.ORDERED, timezone.now()
    po.save()
    audit("po.ordered", actor=request.user, restaurant=request.tenant, obj=po, request=request)
    return po


@transaction.atomic
def receive_po(request, pk, received):
    """received: [{line_id, quantity}]. Partial deliveries are fine; over-receiving is refused."""
    po = _po(request, pk)
    if po.status not in (PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL):
        _fail("Only an ordered purchase order can receive stock.")
    lines = {l.pk: l for l in PurchaseOrderLine.unscoped.select_for_update().filter(order=po).select_related("ingredient")}
    got = 0
    for r in sorted(received, key=lambda r: r["line_id"]):
        line = lines.get(r["line_id"])
        qty = q3(r["quantity"])
        if line is None:
            _fail("Unknown line.", "lines")
        if qty <= 0:
            continue
        if line.received + qty > line.quantity:
            _fail(f"Only {line.quantity - line.received} of {line.ingredient.name} is still expected.", "lines")
        line.received += qty
        line.save(update_fields=["received", "updated_at"])
        move(request.tenant, line.ingredient, po.branch, qty, R.PURCHASE, request.user, po.number, po)
        Ingredient.unscoped.filter(pk=line.ingredient_id).update(last_unit_cost=line.unit_cost)
        got += 1
    if not got:
        _fail("Enter a quantity received.")
    done = all(l.received >= l.quantity for l in lines.values())
    po.status = PurchaseOrder.Status.RECEIVED if done else PurchaseOrder.Status.PARTIAL
    po.save()
    audit("po.received", actor=request.user, restaurant=request.tenant, obj=po, metadata={"status": po.status, "lines": got}, request=request)
    return po


@transaction.atomic
def cancel_po(request, pk, reason):
    po = _po(request, pk)
    if po.status not in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED):
        _fail("A purchase order that has received stock cannot be cancelled.")
    if len(reason.strip()) < 3:
        _fail("Give a reason.", "reason")
    po.status, po.cancel_reason = PurchaseOrder.Status.CANCELLED, reason.strip()[:300]
    po.save()
    audit("po.cancelled", actor=request.user, restaurant=request.tenant, obj=po, metadata={"reason": po.cancel_reason}, request=request)
    return po


@transaction.atomic
def set_recipe(request, product_id, lines):
    from apps.catalog.models import Product

    product = Product.unscoped.filter(pk=product_id, restaurant=request.tenant).first()
    if product is None:
        raise NotFound()
    ids = {l["ingredient_id"] for l in lines}
    if len(ids) != len(lines):
        _fail("Each ingredient can appear once.", "lines")
    found = {i.pk for i in Ingredient.unscoped.filter(restaurant=request.tenant, pk__in=ids, is_active=True)}
    if found != ids:
        _fail("An ingredient is unknown or inactive.", "lines")
    RecipeLine.unscoped.filter(product=product).delete()
    for l in lines:
        RecipeLine.objects.create(restaurant=request.tenant, product=product, ingredient_id=l["ingredient_id"], quantity=Decimal(l["quantity"]).quantize(Decimal("0.0001")))
    audit("recipe.updated", actor=request.user, restaurant=request.tenant, obj=product, metadata={"lines": len(lines)}, request=request)
    return product
