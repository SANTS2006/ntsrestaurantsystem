from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import AuditLog, audit
from apps.catering.models import CateringPayment
from apps.payments.models import Refund

from .conftest import client_for
from .test_phase10_catering import new_req, svc  # noqa: F401  (fixture)
from .test_phase11_payroll import approved, pay
from .test_phase5_orders import clean, shop  # noqa: F401  (fixtures)
from .test_phase8_management import mk_order

R = "/api/v1/reports/"


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


@pytest.fixture
def money(world, svc, shop, clean):  # noqa: F811
    a1, a2 = world["a1"], world["a2"]
    o1, p1 = mk_order(world, a1, "100.00", paid="100.00", cashier=world["cashier_a1"])
    mk_order(world, a2, "50.00", paid="50.00", method="mobile_money", source="cashier")
    mk_order(world, a1, "30.00", status="cancelled")
    mk_order(world, a1, "12.00", status="received")  # accepted but unpaid -> receivable
    Refund.unscoped.create(restaurant=world["a"], branch=a1, payment=p1, order=o1, reference="RF1", amount=Decimal("10.00"), reason="cold", status="succeeded")
    Order_ = type(o1)
    Order_.unscoped.filter(pk=o1.pk).update(amount_paid=Decimal("90.00"))
    req = new_req(world, svc)
    CateringPayment.unscoped.create(restaurant=world["a"], request=req, kind="deposit", amount=Decimal("200.00"), method="cash", received_on=timezone.now().date())
    CateringPayment.unscoped.create(restaurant=world["a"], request=req, kind="refund", amount=Decimal("20.00"), method="cash", received_on=timezone.now().date())
    _, _, rid = approved(world, world["cashier_a1"])
    assert pay(api(world, "mgr_a1"), rid).status_code == 200
    return o1


def test_financial_report_figures(world, money):
    d = api(world, "admin_a").get(R + "finance/").data
    assert d["orders"]["booked"] == "162.00" and d["orders"]["count"] == 3  # cancelled excluded
    assert d["income"]["collected"] == "150.00" and d["income"]["refunds"] == "10.00" and d["income"]["sales_received"] == "140.00"
    assert d["income"]["catering_received"] == "180.00" and d["income"]["total_received"] == "320.00"
    assert d["income"]["by_method"] == {"cash": "100.00", "mobile_money": "50.00"}
    assert d["expenses"]["payroll_paid"] == "1000.00" and d["expenses"]["payroll_records"] == 1
    assert d["operating_result"] == "-680.00"
    assert d["receivables"]["orders"] == "12.00"
    assert sum(Decimal(b["net"]) for b in d["by_branch"]) == Decimal("140.00")
    assert d["trend"][-1]["operating_result"] == "-680.00"
    assert d["notes"] and all(isinstance(v, str) for v in (d["operating_result"], d["income"]["collected"]))


def test_financial_report_is_admin_only_and_tenant_isolated(world, money):
    for who in ("mgr_a1", "cashier_a1", "kitchen_a1", "cust_a"):
        c = api(world, who)
        assert c.get(R + "finance/").status_code == 403
        assert c.get(R + "finance/export/").status_code == 403
        assert c.get(R + "audit/").status_code == 403
    b = api(world, "admin_b", "bravo").get(R + "finance/").data
    assert b["orders"]["count"] == 0 and b["operating_result"] == "0.00" and b["expenses"]["payroll_paid"] == "0.00"
    assert api(world, "admin_a", "bravo").get(R + "finance/").status_code in (401, 403, 404)


def test_range_validation(world, money):
    a = api(world, "admin_a")
    assert a.get(R + "finance/", {"from": "nope"}).status_code == 400
    assert a.get(R + "finance/", {"from": "2024-01-01", "to": "2026-01-01"}).status_code == 400
    old = a.get(R + "finance/", {"from": "2020-01-01", "to": "2020-01-31"}).data
    assert old["income"]["sales_received"] == "0.00"


def test_financial_csv_export_is_audited(world, money):
    r = api(world, "admin_a").get(R + "finance/export/")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    body = r.content.decode()
    assert "operating_result,-" in body.replace("'", "") or "operating_result" in body
    assert "payroll_paid,1000.00" in body
    assert AuditLog.objects.filter(action="report.exported", metadata__type="financial").exists()


def test_analytics_scope_and_shape(world, money):
    mgr = api(world, "mgr_a1")
    d = mgr.get(R + "analytics/").data
    assert len(d["by_hour"]) == 24 and len(d["by_weekday"]) == 7
    assert d["orders"] == 3 and sum(h["orders"] for h in d["by_hour"]) == 2  # a1 only: cancelled counted in orders, not in live buckets
    assert d["average_order_value"] == "56.00"
    assert d["cancellation_rate_percent"] == "33.3"
    assert mgr.get(R + "analytics/", {"branch": world["a2"].pk}).status_code == 404
    adm = api(world, "admin_a").get(R + "analytics/").data
    assert adm["orders"] == 4
    assert {s["source"] for s in adm["by_source"]} >= {"online", "cashier"}
    for who in ("cashier_a1", "cust_a"):
        assert api(world, who).get(R + "analytics/").status_code == 403


def test_tenant_audit_viewer(world, money):
    audit("test.alpha", actor=world["admin_a"], restaurant=world["a"], metadata={"k": "v"})
    audit("test.bravo", actor=world["admin_b"], restaurant=world["b"])
    audit("test.platform", actor=world["platform"])
    a = api(world, "admin_a")
    rows = a.get(R + "audit/", {"page_size": 100}).data["results"]
    acts = {r["action"] for r in rows}
    assert "test.alpha" in acts and "test.bravo" not in acts and "test.platform" not in acts
    assert all("ip_address" not in r for r in rows)
    assert a.get(R + "audit/", {"action": "test."}).data["count"] == 1
    assert a.get(R + "audit/", {"actor": world["admin_a"].pk, "action": "payroll."}).data["count"] >= 1
    assert a.get(R + "audit/", {"from": "bad"}).status_code == 400
    future = (timezone.now().date() + timedelta(days=5)).isoformat()
    assert a.get(R + "audit/", {"from": future}).data["count"] == 0
    assert api(world, "admin_b", "bravo").get(R + "audit/").data["count"] == 1
    assert a.post(R + "audit/", {}, format="json").status_code == 405


def test_platform_report(world, money):
    d = client_for(world["platform"]).get(R + "platform/").data
    names = {r["slug"]: r for r in d["restaurants"]}
    assert names["alpha"]["net"] == "140.00" and names["alpha"]["orders"] == 3 and names["bravo"]["orders"] == 0
    assert d["totals_by_currency"][0]["currency"]
    assert not any("payroll" in k for r in d["restaurants"] for k in r)  # no payroll or customer data at platform level
    assert d["new_restaurants_by_month"]
    # restaurant administrators and staff cannot read platform-wide figures, neither on their host nor the platform host
    assert api(world, "admin_a").get(R + "platform/").status_code == 403
    assert client_for(world["admin_a"]).get(R + "platform/").status_code == 403
    assert client_for(world["platform"], "alpha").get(R + "platform/").status_code == 403


def test_platform_audit_filters(world, money):
    audit("zzz.event", actor=world["admin_a"], restaurant=world["a"])
    p = client_for(world["platform"])
    base = "/api/v1/platform/audit-logs/"
    assert p.get(base, {"actor": "admin@a.com", "action": "zzz"}).data["count"] == 1
    assert p.get(base, {"actor": "nobody@x.com"}).data["count"] == 0
    assert p.get(base, {"from": "oops"}).status_code == 400
    future = (timezone.now().date() + timedelta(days=3)).isoformat()
    assert p.get(base, {"from": future}).data["count"] == 0
    assert client_for(world["admin_a"]).get(base).status_code == 403
