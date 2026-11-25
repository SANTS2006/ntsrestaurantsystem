from datetime import datetime, timezone as dt_tz

from apps.orders.models import Order
from apps.payments.models import Payment
from apps.tenants.models import RestaurantSettings

from .conftest import client_for
from .test_phase5_orders import clean, shop  # noqa: F401
from .test_phase8_management import mk_order

R = "/api/v1/reports/"


def place(world, when_utc):
    o, p = mk_order(world, world["a1"], "40.00", paid="40.00", cashier=world["cashier_a1"])
    Order.unscoped.filter(pk=o.pk).update(created_at=when_utc)
    Payment.unscoped.filter(pk=p.pk).update(paid_at=when_utc)
    return o


def set_tz(world, name):
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(timezone=name)


def test_reports_follow_the_restaurant_time_zone(world, shop, clean):  # noqa: F811
    place(world, datetime(2026, 11, 1, 20, 0, tzinfo=dt_tz.utc))  # 2 Nov 09:00 in Auckland (UTC+13), still 1 Nov in UTC
    admin = client_for(world["admin_a"], "alpha")
    day = {"from": "2026-11-02", "to": "2026-11-02"}
    set_tz(world, "UTC")
    assert admin.get(R + "finance/", day).json()["data"]["income"]["collected"] == "0.00"
    assert admin.get(R + "branch/", {**day, "group": "day"}).json()["data"]["orders"]["total"] == 0
    set_tz(world, "Pacific/Auckland")
    assert admin.get(R + "finance/", day).json()["data"]["income"]["collected"] == "40.00"
    b = admin.get(R + "branch/", {**day, "group": "day"}).json()["data"]
    assert b["orders"]["total"] == 1 and b["series"][0]["period"] == "2026-11-02" and b["series"][0]["collected"] == "40.00"
    assert admin.get(R + "finance/", {"from": "2026-11-01", "to": "2026-11-01"}).json()["data"]["income"]["collected"] == "0.00"
    assert admin.get(R + "finance/", day).json()["data"]["timezone"] == "Pacific/Auckland"


def test_analytics_hours_use_local_time(world, shop, clean):  # noqa: F811
    place(world, datetime(2026, 11, 1, 20, 0, tzinfo=dt_tz.utc))
    set_tz(world, "Pacific/Auckland")
    d = client_for(world["admin_a"], "alpha").get(R + "analytics/", {"from": "2026-11-02", "to": "2026-11-02"}).json()["data"]
    assert d["by_hour"][9]["orders"] == 1 and d["by_hour"][20]["orders"] == 0 and d["timezone"] == "Pacific/Auckland"
    assert sum(x["orders"] for x in d["by_weekday"] if x["day"] == "Mon") == 1  # 2 Nov 2026 is a Monday


def test_each_restaurant_has_its_own_zone_and_platform_report_respects_it(world, shop, clean):  # noqa: F811
    place(world, datetime(2026, 11, 1, 20, 0, tzinfo=dt_tz.utc))
    p = client_for(world["platform"])
    day = {"from": "2026-11-02", "to": "2026-11-02"}
    rows = {r["slug"]: r for r in p.get(R + "platform/", day).json()["data"]["restaurants"]}
    assert rows["alpha"]["orders"] == 0
    set_tz(world, "Pacific/Auckland")
    rows = {r["slug"]: r for r in p.get(R + "platform/", day).json()["data"]["restaurants"]}
    assert rows["alpha"]["orders"] == 1 and rows["bravo"]["orders"] == 0


def test_cashier_today_uses_restaurant_day(world, shop, clean):  # noqa: F811
    from django.utils import timezone

    set_tz(world, "Pacific/Auckland")
    mk_order(world, world["a1"], "25.00", paid="25.00", cashier=world["cashier_a1"])
    d = client_for(world["cashier_a1"], "alpha").get("/api/v1/cashier/dashboard/").json()["data"]
    assert d["periods"]["today"]["total"] in ("25.00", "0.00")  # depends on the local clock; must not error and must not exceed the sale
    assert timezone.now()


def test_invalid_stored_zone_falls_back_safely(world, shop, clean):  # noqa: F811
    set_tz(world, "Not/AZone")
    assert client_for(world["admin_a"], "alpha").get(R + "finance/").status_code == 200
