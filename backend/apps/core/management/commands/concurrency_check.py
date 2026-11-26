"""Concurrency invariants for ordering, run against the CONFIGURED database.

Why a command: row locks (`select_for_update`) only do real work on PostgreSQL. SQLite serialises all writers, so the
test-suite cannot prove locking. Run this against a staging PostgreSQL database (NEVER production: it creates a clearly
named, suspended test restaurant with orders that cannot be deleted):

    python manage.py concurrency_check --threads 20 --i-understand-this-writes-test-data

Checks (each prints PASS/FAIL, exit code 1 on any failure):
  A. Stock cannot be oversold: stock 5, N parallel orders for 1 unit each -> exactly 5 succeed, stock ends at 0,
     stock movements sum to -5, nobody gets a server error.
  B. Idempotency under a race: the same Idempotency-Key sent N times in parallel creates exactly one order.
  C. Order numbers are unique across all of the above.
"""
import secrets
import threading
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections
from django.test import override_settings
from rest_framework.test import APIClient


class Command(BaseCommand):
    help = "Run concurrent ordering scenarios and verify stock and idempotency invariants (use on staging PostgreSQL)."

    def add_arguments(self, parser):
        parser.add_argument("--threads", type=int, default=20)
        parser.add_argument("--i-understand-this-writes-test-data", action="store_true", dest="confirmed")
        parser.add_argument("--allow-sqlite", action="store_true", help="Run anyway on SQLite (proves logic only, not row locking).")

    def handle(self, *args, **o):
        if not o["confirmed"]:
            raise CommandError("Add --i-understand-this-writes-test-data (staging databases only).")
        if connection.vendor != "postgresql" and not o["allow_sqlite"]:
            raise CommandError("This check is only meaningful on PostgreSQL. Use --allow-sqlite to run the logic anyway.")
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("SQLite serialises writers: this does NOT prove row locking."))
        n = max(4, min(o["threads"], 100))
        with override_settings(ALLOWED_HOSTS=["*"]):
            ok = self.run_all(n)
        if not ok:
            raise CommandError("Concurrency invariants FAILED.")
        self.stdout.write(self.style.SUCCESS("All concurrency invariants held."))

    # ---------------------------------------------------------------------------------------------------
    def setup(self, n):
        from apps.accounts.models import Membership, Role, User
        from apps.catalog.models import Category, Product
        from apps.tenants.models import Branch, Restaurant, RestaurantSettings

        tag = secrets.token_hex(3)
        r = Restaurant.objects.create(name=f"ZZ concurrency-check {tag}", slug=f"cc-{tag}", status="suspended")
        RestaurantSettings.objects.create(restaurant=r, currency="SLE", tax_rate_percent=Decimal("0"), delivery_fee=Decimal("0"))
        r.status = "active"  # must be active to take orders; it is suspended again at the end
        r.save()
        branch = Branch.unscoped.create(restaurant=r, name="CC", code="CC")
        cat = Category.unscoped.create(restaurant=r, name="CC", slug="cc")
        tight = Product.unscoped.create(restaurant=r, category=cat, name="Tight", slug="tight", base_price=Decimal("5.00"), track_inventory=True, stock_quantity=5)
        plenty = Product.unscoped.create(restaurant=r, category=cat, name="Plenty", slug="plenty", base_price=Decimal("5.00"), track_inventory=True, stock_quantity=1000)
        users = []
        for i in range(n):
            u = User.objects.create_user(f"cc-{tag}-{i}@example.invalid", secrets.token_urlsafe(16), full_name=f"CC {i}", email_verified=True)
            Membership.objects.create(user=u, restaurant=r, role=Role.CUSTOMER)
            users.append(u)
        return r, branch, tight, plenty, users

    def post(self, restaurant, user, product, branch, key, out, idx):
        try:
            c = APIClient(HTTP_HOST=f"{restaurant.slug}.{settings.PLATFORM_DOMAIN}")
            c.force_authenticate(user)
            r = c.post("/api/v1/orders/checkout/", {"items": [{"product_id": product.pk, "quantity": 1}], "fulfilment": "pickup", "payment_method": "cash",
                                                   "contact_phone": "+23276123456", "branch_id": branch.pk}, format="json", HTTP_IDEMPOTENCY_KEY=key)
            out[idx] = (r.status_code, (r.json().get("data") or {}).get("number") if r.status_code < 300 else None)
        except Exception as e:  # noqa: BLE001
            out[idx] = (599, repr(e)[:100])
        finally:
            connections.close_all()

    def fan_out(self, targets):
        out = [None] * len(targets)
        ts = [threading.Thread(target=self.post, args=(*t, out, i)) for i, t in enumerate(targets)]
        gate = threading.Barrier(len(ts))

        def wrap(th, fn):
            def run():
                gate.wait()
                fn()
            return run
        ts = [threading.Thread(target=wrap(t, t.run)) for t in ts]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return out

    def run_all(self, n):
        from apps.catalog.models import Product, StockMovement
        from apps.orders.models import Order
        from apps.tenants.models import Restaurant

        r, branch, tight, plenty, users = self.setup(n)
        ok = True

        def check(name, cond, detail=""):
            nonlocal ok
            ok &= bool(cond)
            self.stdout.write((self.style.SUCCESS("PASS ") if cond else self.style.ERROR("FAIL ")) + name + (f"  [{detail}]" if detail else ""))

        # A: oversell
        res = self.fan_out([(r, users[i], tight, branch, f"A-{i}-{secrets.token_hex(4)}") for i in range(n)])
        good = [x for x in res if x[0] == 201]
        errs = [x for x in res if x[0] >= 500]
        tight.refresh_from_db()
        moved = sum(StockMovement.unscoped.filter(restaurant=r, product=tight).values_list("delta", flat=True))
        check("A. exactly 5 orders succeed for 5 units of stock", len(good) == 5, f"{len(good)} succeeded of {n}")
        check("A. stock ends at 0 and never negative", tight.stock_quantity == 0, f"stock={tight.stock_quantity}")
        check("A. stock movements sum to -5", moved == -5, f"sum={moved}")
        check("A. no server errors", not errs, str(errs[:3]))

        # B: idempotency race
        key = f"B-{secrets.token_hex(6)}"
        res = self.fan_out([(r, users[0], plenty, branch, key) for _ in range(n)])
        created = Order.unscoped.filter(restaurant=r, customer=users[0], items__product=plenty).distinct().count()
        numbers = {x[1] for x in res if x[0] in (200, 201)}
        check("B. one order for N identical idempotent requests", created == 1, f"orders={created}")
        check("B. every replay returns that same order", len(numbers) == 1, f"numbers={numbers}")
        check("B. no server errors", not [x for x in res if x[0] >= 500], str([x for x in res if x[0] >= 500][:3]))
        plenty = Product.unscoped.get(pk=plenty.pk)
        check("B. stock was taken once", plenty.stock_quantity == 999, f"stock={plenty.stock_quantity}")

        # C: unique numbers
        nums = list(Order.unscoped.filter(restaurant=r).values_list("number", flat=True))
        check("C. order numbers are unique", len(nums) == len(set(nums)), f"{len(nums)} orders")

        Restaurant.objects.filter(pk=r.pk).update(status="suspended")
        self.stdout.write(f"Test restaurant left suspended: slug={r.slug}")
        return ok
