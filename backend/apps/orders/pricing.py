"""Authoritative price calculation. The browser only ever sends *what* the customer wants (ids and
quantities); every amount is computed here from current catalog data, in Decimal."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from apps.catalog.models import Product

MAX_LINES = 50
MAX_QTY = 50
CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


class AddonInput(serializers.Serializer):
    id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QTY, default=1)


class LineInput(serializers.Serializer):
    product_id = serializers.IntegerField()
    variation_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QTY)
    addons = AddonInput(many=True, required=False, default=list)
    instructions = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


@dataclass
class PricedLine:
    product: Product
    variation: object
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    addons: list
    instructions: str


@dataclass
class Quote:
    lines: list = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    discount_total: Decimal = Decimal("0.00")
    tax_total: Decimal = Decimal("0.00")
    delivery_fee: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    tax_rate_percent: Decimal = Decimal("0.00")
    currency: str = ""

    def as_dict(self):
        return {
            "currency": self.currency, "subtotal": str(self.subtotal), "discount_total": str(self.discount_total),
            "tax_rate_percent": str(self.tax_rate_percent), "tax_total": str(self.tax_total),
            "delivery_fee": str(self.delivery_fee), "total": str(self.total),
            "lines": [{"product_id": l.product.pk, "name": l.product.name, "variation": l.variation.name if l.variation else "",
                       "quantity": l.quantity, "unit_price": str(l.unit_price), "line_total": str(l.line_total),
                       "addons": l.addons, "instructions": l.instructions} for l in self.lines],
        }


def price_cart(restaurant, lines, fulfilment, *, lock=False, discount=None, max_discount_percent=None) -> Quote:
    """Validate cart lines against the live catalog and compute every amount.

    With ``lock=True`` (checkout) the product rows are locked in id order so concurrent orders
    cannot oversell tracked stock, and stock is verified against the locked quantities.
    """
    if not lines:
        raise serializers.ValidationError({"items": "Your cart is empty."})
    if len(lines) > MAX_LINES:
        raise serializers.ValidationError({"items": f"A cart can hold at most {MAX_LINES} lines."})
    settings = restaurant.get_settings()
    if fulfilment == "delivery" and not settings.delivery_enabled:
        raise serializers.ValidationError({"fulfilment": "Delivery is not available."})
    if fulfilment == "pickup" and not settings.pickup_enabled:
        raise serializers.ValidationError({"fulfilment": "Pickup is not available."})

    ids = sorted({l["product_id"] for l in lines})
    qs = Product.unscoped.filter(restaurant=restaurant, pk__in=ids, is_archived=False, is_available=True,
                                 category__is_active=True).select_related("category").prefetch_related("variations", "addons")
    if lock:
        qs = qs.select_for_update(of=("self",)).order_by("pk")
    products = {p.pk: p for p in qs}
    wanted_stock: dict[int, int] = {}
    quote = Quote(currency=settings.currency, tax_rate_percent=settings.tax_rate_percent)

    for i, l in enumerate(lines):
        p = products.get(l["product_id"])  # other tenants' / archived / hidden products simply do not exist here
        if p is None:
            raise serializers.ValidationError({"items": f"Item {i + 1} is no longer available."})
        variations = {v.pk: v for v in p.variations.all() if v.is_available}
        variation = None
        if l["variation_id"] is not None:
            variation = variations.get(l["variation_id"])
            if variation is None:
                raise serializers.ValidationError({"items": f"Invalid option for {p.name}."})
        elif variations:
            variation = next((v for v in variations.values() if v.is_default), None)
            if variation is None:
                raise serializers.ValidationError({"items": f"Please choose an option for {p.name}."})
        addons_by_id = {a.pk: a for a in p.addons.all() if a.is_available}
        chosen, seen = [], set()
        for a in l["addons"]:
            addon = addons_by_id.get(a["id"])
            if addon is None or a["id"] in seen:
                raise serializers.ValidationError({"items": f"Invalid extra for {p.name}."})
            if a["quantity"] > addon.max_quantity:
                raise serializers.ValidationError({"items": f"At most {addon.max_quantity} of {addon.name}."})
            seen.add(a["id"])
            chosen.append({"id": addon.pk, "name": addon.name, "price": str(addon.price), "quantity": a["quantity"]})
        if l["instructions"] and not p.allow_instructions:
            raise serializers.ValidationError({"items": f"{p.name} does not accept special instructions."})

        unit = p.effective_price + (variation.price_delta if variation else Decimal("0"))
        unit += sum((Decimal(c["price"]) * c["quantity"] for c in chosen), Decimal("0"))
        unit = money(unit)
        quote.lines.append(PricedLine(p, variation, l["quantity"], unit, money(unit * l["quantity"]), chosen, l["instructions"]))
        if p.track_inventory:
            wanted_stock[p.pk] = wanted_stock.get(p.pk, 0) + l["quantity"]

    for pid, qty in wanted_stock.items():
        if products[pid].stock_quantity < qty:
            raise serializers.ValidationError({"items": f"Only {products[pid].stock_quantity} of {products[pid].name} left."})

    quote.subtotal = money(sum((l.line_total for l in quote.lines), Decimal("0")))
    if discount:  # staff-entered only; the public endpoints never pass one
        value = Decimal(str(discount["value"]))
        amount = money(quote.subtotal * value / Decimal(100)) if discount["type"] == "percent" else money(value)
        if amount <= 0:
            raise serializers.ValidationError({"discount": "The discount must be more than zero."})
        if amount > quote.subtotal:
            raise serializers.ValidationError({"discount": "The discount cannot be more than the order subtotal."})
        pct = (amount * 100 / quote.subtotal) if quote.subtotal else Decimal(0)
        if max_discount_percent is not None and pct > Decimal(max_discount_percent):
            raise serializers.ValidationError({"discount": f"Discounts above {max_discount_percent}% need a manager."})
        quote.discount_total = amount
    quote.tax_total = money((quote.subtotal - quote.discount_total) * settings.tax_rate_percent / Decimal(100))  # tax is charged on the discounted amount
    quote.delivery_fee = money(settings.delivery_fee) if fulfilment == "delivery" else Decimal("0.00")
    quote.total = money(quote.subtotal - quote.discount_total + quote.tax_total + quote.delivery_fee)
    return quote


class DiscountInput(serializers.Serializer):
    type = serializers.ChoiceField(choices=["percent", "amount"])
    value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reason = serializers.CharField(max_length=200)

    def validate(self, a):
        if a["type"] == "percent" and a["value"] > 100:
            raise serializers.ValidationError({"value": "A percentage cannot exceed 100."})
        a["reason"] = a["reason"].strip()
        if len(a["reason"]) < 3:
            raise serializers.ValidationError({"reason": "Give a reason for the discount."})
        return a
