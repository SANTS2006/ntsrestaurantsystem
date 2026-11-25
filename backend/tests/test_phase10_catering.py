import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from tests.conftest import TenantClient as APIClient

from apps.catalog.models import Service
from apps.catering.models import CateringNote, CateringPayment, CateringRequest, Quotation
from apps.core.models import AuditLog
from apps.notifications.providers import ConsoleProvider
from apps.tenants.models import Branch

from .conftest import client_for, host
from .test_phase5_orders import clean, shop  # noqa: F401  (fixtures: restaurant settings with 8.25% tax)

C = "/api/v1/catering/"


def today():
    return timezone.now().date()


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def pub(slug="alpha"):
    return APIClient(HTTP_HOST=host(slug))


@pytest.fixture
def svc(world, shop):
    world["a"].contact_email = "events@alpha.test"
    world["a"].save()
    return {"wedding": Service.unscoped.create(restaurant=world["a"], name="Wedding catering", slug="wedding"),
            "hidden": Service.unscoped.create(restaurant=world["a"], name="Hidden", slug="hidden", is_active=False),
            "b": Service.unscoped.create(restaurant=world["b"], name="Bravo svc", slug="bsvc")}


def body(svc, **over):
    return {"customer_name": "Dana Okoro", "customer_email": "Dana@Example.com", "customer_phone": "+23276123456", "event_type": "wedding",
            "event_date": (today() + timedelta(days=40)).isoformat(), "event_location": "Beach Hotel, Freetown", "guests": 120,
            "service_ids": [svc["wedding"].pk], "food_preferences": "no pork", "budget": "5000.00", "requirements": "outdoor setup",
            "accept_privacy": True, **over}


def submit(svc, slug="alpha", **over):
    return pub(slug).post(C + "public/requests/", body(svc, **over), format="json")


def mails(to=None):
    return [m for m in ConsoleProvider.outbox if to is None or m["to"] == to]


def new_req(world, svc, branch="a1", **over):
    r = submit(svc, branch_id=world[branch].pk if branch else None, **over)
    assert r.status_code == 201, r.data
    return CateringRequest.unscoped.get(reference=r.data["reference"])


def staff_post(world, who, pk, path, data=None, **kw):
    return api(world, who).post(f"{C}requests/{pk}/{path}/", data or {}, format="json", **kw)


# =========================== public form ==========================================================
def test_public_options_list_only_active_services_and_branches_of_this_restaurant(world, svc):
    d = json.loads(pub().get(C + "public/options/").content)["data"]
    assert [s["name"] for s in d["services"]] == ["Wedding catering"]
    assert {b["name"] for b in d["branches"]} == {"A One", "A Two"} and d["currency"] == "USD"
    assert "wedding" in [e["value"] for e in d["event_types"]]
    assert APIClient(HTTP_HOST=host()).get(C + "public/options/").status_code == 404  # platform host


def test_valid_request_is_stored_numbered_emailed_and_logged(world, svc):
    r = submit(svc, branch_id=world["a1"].pk)
    assert r.status_code == 201 and r.data["reference"] == "CAT-000001"
    req = CateringRequest.unscoped.get()
    assert (req.status, req.branch_id, req.customer_email, req.currency, req.guests) == ("new", world["a1"].pk, "dana@example.com", "USD", 120)
    assert [s.name for s in req.services.all()] == ["Wedding catering"] and req.consent_at and req.client_hash and "." not in req.client_hash
    assert [h.to_status for h in req.history.all()] == ["new"]
    cust = mails("dana@example.com")[0]
    assert "CAT-000001" in cust["html"] and "not a booking confirmation" in cust["html"]
    staff = mails("events@alpha.test")[0]
    assert "dana" not in staff["html"].lower() and "+2327" not in staff["html"]  # the alert carries no customer contact details
    assert AuditLog.objects.filter(action="catering.request_created").count() == 1
    assert submit(svc).data["reference"] == "CAT-000002"
    assert submit(svc, slug="bravo", service_ids=[]).data["reference"] == "CAT-000001"  # numbering is per restaurant


@pytest.mark.parametrize("over", [
    {"event_date": (today() - timedelta(days=1)).isoformat()}, {"event_date": today().isoformat()},
    {"event_date": (today() + timedelta(days=800)).isoformat()}, {"event_date": "soon"},
    {"guests": 0}, {"guests": 5001}, {"customer_email": "nope"}, {"customer_phone": "call me"}, {"customer_name": ""},
    {"accept_privacy": False}, {"website": "http://spam.example"}, {"budget": "-5"}, {"event_type": "rave"},
    {"event_location": ""}, {"requirements": "x" * 3001},
])
def test_invalid_public_requests_are_rejected(world, svc, over):
    assert submit(svc, **over).status_code == 400
    assert CateringRequest.unscoped.count() == 0 and mails() == []


def test_services_and_branches_must_belong_to_this_restaurant_and_be_active(world, svc):
    assert submit(svc, service_ids=[svc["b"].pk]).status_code == 400      # another restaurant's service
    assert submit(svc, service_ids=[svc["hidden"].pk]).status_code == 400  # inactive
    assert submit(svc, branch_id=world["b1"].pk).status_code == 400        # another restaurant's branch
    Branch.unscoped.filter(pk=world["a2"].pk).update(status="suspended")
    assert submit(svc, branch_id=world["a2"].pk).status_code == 400
    assert submit(svc, branch_id=None).status_code == 201                  # branch is optional


def test_public_submission_is_throttled(world, svc, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"catering": "2/hour"})
    cache.clear()
    assert [submit(svc).status_code for _ in range(4)] == [201, 201, 429, 429]
    cache.clear()


# =========================== staff access =========================================================
def test_catering_is_for_managers_and_admins_only_and_scoped_by_branch(world, svc):
    r1, r2, r0 = new_req(world, svc, "a1"), new_req(world, svc, "a2"), new_req(world, svc, None)
    ids = lambda who: sorted(x["id"] for x in api(world, who).get(C + "requests/").data["results"])  # noqa: E731
    assert ids("admin_a") == sorted([r1.pk, r2.pk, r0.pk])
    assert ids("mgr_a1") == [r1.pk] and ids("mgr_a2") == [r2.pk]  # unallocated requests are admin-only until a branch is chosen
    for who in ("cashier_a1", "kitchen_a1", "cust_a"):
        assert api(world, who).get(C + "requests/").status_code == 403
    assert api(world, "mgr_a1").get(f"{C}requests/{r2.pk}/").status_code == 404
    assert api(world, "mgr_a1").get(f"{C}requests/{r0.pk}/").status_code == 404
    assert api(world, "admin_b", "bravo").get(f"{C}requests/{r1.pk}/").status_code == 404
    assert api(world, "admin_b", "bravo").get(C + "requests/").data["results"] == []
    assert pub().get(C + "requests/").status_code == 401
    d = api(world, "mgr_a1").get(C + "requests/").data
    assert d["counts"]["new"] == 1 and d["counts"]["accepted"] == 0
    full = api(world, "mgr_a1").get(f"{C}requests/{r1.pk}/").data
    assert full["customer_email"] == "dana@example.com" and full["services"] == ["Wedding catering"] and full["balance"]["balance"] == "0.00"
    assert [x["id"] for x in api(world, "admin_a").get(C + "requests/", {"unallocated": "1"}).data["results"]] == [r0.pk]
    assert [x["id"] for x in api(world, "admin_a").get(C + "requests/", {"q": r2.reference}).data["results"]] == [r2.pk]


# =========================== status machine =======================================================
def test_status_machine_allows_only_legal_moves_and_requires_reasons(world, svc):
    r = new_req(world, svc)
    st = lambda to, note="": staff_post(world, "mgr_a1", r.pk, "status", {"status": to, "note": note})  # noqa: E731
    for bad in ("in_progress", "completed", "accepted", "quotation_sent", "new", "nonsense"):
        assert st(bad).status_code == 400, bad
    assert st("under_review").data["status"] == "under_review"
    assert st("rejected").status_code == 400  # reason required
    assert any("catering request" in m["subject"].lower() and "Under Review" in m["subject"] for m in mails("dana@example.com"))
    rej = st("rejected", "fully booked that weekend")
    assert rej.status_code == 200 and rej.data["status"] == "rejected" and rej.data["cancel_reason"] == "fully booked that weekend"
    assert "fully booked" in mails("dana@example.com")[-1]["html"]
    for to in ("under_review", "cancelled", "in_progress"):
        assert st(to, "x").status_code == 400  # terminal
    assert [h["status"] for h in api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").data["history"]] == ["new", "under_review", "rejected"]
    assert AuditLog.objects.filter(action="catering.status_changed").count() == 2


def test_allowed_status_buttons_reflect_the_state(world, svc):
    r = new_req(world, svc)
    assert [s["status"] for s in api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").data["allowed_statuses"]] == ["cancelled", "rejected", "under_review"]


# =========================== assignment, notes, contact ===========================================
def test_assign_staff_and_branch_rules(world, svc):
    r = new_req(world, svc, "a1")
    ok = staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": world["cashier_a1"].pk})
    assert ok.status_code == 200 and ok.data["assigned_to"] == "cash1"
    assert staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": world["cashier_a2"].pk}).status_code == 400  # works at another branch
    assert staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": world["cust_a"].pk}).status_code == 400      # a customer
    assert staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": world["admin_b"].pk}).status_code == 400     # another restaurant
    assert staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": "x"}).status_code == 400
    assert staff_post(world, "admin_a", r.pk, "assign", {"user_id": world["admin_a"].pk}).status_code == 200    # admins can take any request
    assert staff_post(world, "mgr_a1", r.pk, "assign", {"user_id": None}).data["assigned_to"] is None
    assert CateringNote.unscoped.filter(request=r, text__startswith="Assigned to").count() == 3
    assert staff_post(world, "mgr_a2", r.pk, "assign", {"user_id": None}).status_code == 404


def test_only_the_admin_allocates_branches(world, svc):
    r = new_req(world, svc, None)
    assert staff_post(world, "mgr_a1", r.pk, "set-branch", {"branch_id": world["a1"].pk}).status_code == 404  # cannot even see it
    assert staff_post(world, "admin_a", r.pk, "set-branch", {"branch_id": world["a1"].pk}).data["branch"]["id"] == world["a1"].pk
    assert staff_post(world, "mgr_a1", r.pk, "set-branch", {"branch_id": world["a2"].pk}).status_code == 400  # managers cannot move requests
    assert staff_post(world, "admin_a", r.pk, "set-branch", {"branch_id": world["b1"].pk}).status_code == 400
    assert api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").status_code == 200  # now visible to the branch manager


def test_internal_notes_are_staff_only_and_immutable(world, svc):
    r = new_req(world, svc)
    n = staff_post(world, "mgr_a1", r.pk, "notes", {"text": "VIP, call before 5pm"})
    assert n.status_code == 200 and n.data["notes"][0]["text"] == "VIP, call before 5pm" and n.data["notes"][0]["author"] == "mgr1"
    assert staff_post(world, "mgr_a1", r.pk, "notes", {"text": ""}).status_code == 400
    assert staff_post(world, "cashier_a1", r.pk, "notes", {"text": "x"}).status_code == 403
    note = CateringNote.unscoped.get()
    with pytest.raises(PermissionError):
        note.delete()
    note.text = "tampered"
    with pytest.raises(PermissionError):
        note.save()
    assert "VIP" not in str(mails())  # never leaves the building


def test_contacting_the_customer_is_escaped_logged_and_rate_limited(world, svc):
    r = new_req(world, svc)
    ConsoleProvider.outbox.clear()
    ok = staff_post(world, "mgr_a1", r.pk, "contact", {"subject": "Menu\nquestions", "message": "Hi <script>alert(1)</script>\nCan we call?"})
    assert ok.status_code == 200
    m = mails("dana@example.com")[0]
    assert m["subject"] == "Menu questions" and "<script>" not in m["html"] and "&lt;script&gt;" in m["html"] and "<br>" in m["html"]
    log = [n for n in ok.data["notes"] if n["kind"] == "email"]
    assert len(log) == 1 and "Can we call" in log[0]["text"]
    for _ in range(9):
        staff_post(world, "mgr_a1", r.pk, "contact", {"subject": "s", "message": "m"})
    assert staff_post(world, "mgr_a1", r.pk, "contact", {"subject": "s", "message": "m"}).status_code == 400
    assert staff_post(world, "mgr_a1", r.pk, "contact", {"subject": "", "message": "m"}).status_code == 400
    cache.clear()


# =========================== quotations ===========================================================
def quote_body(**over):
    return {"items": [{"description": "Buffet for 120", "quantity": "120", "unit_price": "25.00"}, {"description": "Staff", "quantity": "2.5", "unit_price": "40.00"}],
            "discount": "100.00", "valid_until": (today() + timedelta(days=14)).isoformat(), "terms": "50% deposit to confirm.", **over}


def make_quote(world, r, who="mgr_a1", **over):  # noqa: D103
    resp = api(world, who).post(f"{C}requests/{r.pk}/quotations/", quote_body(**over), format="json")
    assert resp.status_code == 200, resp.data
    return resp.data["quotations"][0]


def token_of(to="dana@example.com"):
    return re.search(r"/quotation/([\w-]+)", [m for m in mails(to) if "/quotation/" in m["html"]][-1]["html"]).group(1)


def test_quotation_totals_are_computed_by_the_server(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r, total="1.00", subtotal="1.00", tax_total="0.00")
    # 120 x 25.00 = 3000.00 ; 2.5 x 40.00 = 100.00 ; subtotal 3100.00 ; discount 100.00 ; tax 8.25% of 3000.00 = 247.50
    assert [i["line_total"] for i in q["items"]] == ["3000.00", "100.00"]
    assert [i["quantity"] for i in q["items"]] == ["120", "2.5"]  # plain numbers, never scientific notation
    assert (q["subtotal"], q["discount"], q["tax_total"], q["total"], q["status"], q["version"]) == ("3100.00", "100.00", "247.50", "3247.50", "draft", 1)
    assert make_quote(world, r)["version"] == 2


@pytest.mark.parametrize("over", [
    {"items": []}, {"discount": "99999.00"}, {"valid_until": (today() - timedelta(days=1)).isoformat()},
    {"valid_until": (today() + timedelta(days=400)).isoformat()},
    {"items": [{"description": "x", "quantity": "0", "unit_price": "1"}]}, {"items": [{"description": "x", "quantity": "1", "unit_price": "-1"}]},
    {"items": [{"description": "", "quantity": "1", "unit_price": "1"}]},
])
def test_invalid_quotations_are_rejected(world, svc, over):
    r = new_req(world, svc)
    assert api(world, "mgr_a1").post(f"{C}requests/{r.pk}/quotations/", quote_body(**over), format="json").status_code == 400
    assert Quotation.unscoped.count() == 0


def test_sending_a_quotation_emails_a_private_link_and_stores_only_its_hash(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r)
    ConsoleProvider.outbox.clear()
    resp = staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send")
    assert resp.status_code == 200 and resp.data["status"] == "quotation_sent" and resp.data["quotations"][0]["status"] == "sent"
    token = token_of()
    stored = Quotation.unscoped.get()
    assert stored.token_hash and token not in stored.token_hash and stored.token_hash != token
    assert "3247.50" in mails("dana@example.com")[-1]["html"]
    assert [h["status"] for h in resp.data["history"]] == ["new", "under_review", "quotation_sent"]  # auto-reviewed on first quotation
    assert staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send").status_code == 400  # not twice
    assert staff_post(world, "mgr_a2", r.pk, f"quotations/{q['id']}/send").status_code == 404


def test_customer_views_and_accepts_the_quotation_with_the_link(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r)
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send")
    token = token_of()
    v = json.loads(pub().get(f"{C}public/quotations/{token}/").content)["data"]
    assert v["total"] == "3247.50" and v["reference"] == r.reference and v["restaurant"] == "Alpha" and not v["expired"]
    blob = json.dumps(v)
    assert "created_by" not in blob and "dana@example.com" not in blob and "notes" not in blob  # nothing internal or personal leaks
    assert pub().get(f"{C}public/quotations/not-a-token/").status_code == 404
    assert pub("bravo").get(f"{C}public/quotations/{token}/").status_code == 404  # works only on the restaurant's own website
    assert APIClient(HTTP_HOST=host()).get(f"{C}public/quotations/{token}/").status_code == 404
    ConsoleProvider.outbox.clear()
    ok = pub().post(f"{C}public/quotations/{token}/accept/", {"note": "Looking forward to it"}, format="json")
    assert ok.status_code == 200
    r.refresh_from_db()
    quote = Quotation.unscoped.get()
    assert (r.status, quote.status, quote.accepted_via, quote.token_hash) == ("accepted", "accepted", "customer_link", None)
    assert pub().get(f"{C}public/quotations/{token}/").status_code == 404                     # link is single-use
    assert pub().post(f"{C}public/quotations/{token}/accept/", {}, format="json").status_code == 404
    assert any("Accepted" in m["subject"] for m in mails("dana@example.com")) and mails("events@alpha.test")
    assert api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").data["balance"]["agreed_total"] == "3247.50"


def test_declining_returns_the_request_to_review_and_a_new_quote_can_be_sent(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r)
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send")
    token = token_of()
    assert pub().post(f"{C}public/quotations/{token}/decline/", {"note": "Too expensive"}, format="json").status_code == 200
    r.refresh_from_db()
    assert r.status == "under_review" and Quotation.unscoped.get().status == "declined"
    assert pub().get(f"{C}public/quotations/{token}/").status_code == 404
    q2 = make_quote(world, r, discount="500.00")
    assert staff_post(world, "mgr_a1", r.pk, f"quotations/{q2['id']}/send").data["status"] == "quotation_sent"
    assert "Too expensive" in str(api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").data["history"])


def test_a_newer_quotation_voids_the_old_link_and_cancelling_voids_the_current_one(world, svc):
    r = new_req(world, svc)
    q1 = make_quote(world, r)
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q1['id']}/send")
    t1 = token_of()
    q2 = make_quote(world, r, discount="0")
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q2['id']}/send")
    t2 = token_of()
    assert t1 != t2 and pub().get(f"{C}public/quotations/{t1}/").status_code == 404 and pub().get(f"{C}public/quotations/{t2}/").status_code == 200
    assert sorted(Quotation.unscoped.values_list("status", flat=True)) == ["sent", "superseded"]
    assert staff_post(world, "mgr_a1", r.pk, "status", {"status": "cancelled", "note": "event cancelled"}).status_code == 200
    assert pub().post(f"{C}public/quotations/{t2}/accept/", {}, format="json").status_code == 404  # cannot accept a cancelled request


def test_expired_quotations_cannot_be_accepted_or_sent(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r)
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send")
    token = token_of()
    Quotation.unscoped.update(valid_until=today() - timedelta(days=1))
    assert pub().post(f"{C}public/quotations/{token}/accept/", {}, format="json").status_code == 400
    assert json.loads(pub().get(f"{C}public/quotations/{token}/").content)["data"]["expired"] is True
    assert CateringRequest.unscoped.get().status == "quotation_sent"
    q2 = make_quote(world, r)
    Quotation.unscoped.filter(pk=q2["id"]).update(valid_until=today() - timedelta(days=1))
    assert staff_post(world, "mgr_a1", r.pk, f"quotations/{q2['id']}/send").status_code == 400



def test_staff_can_record_a_phone_acceptance_only_with_a_note(world, svc):
    r = new_req(world, svc)
    q = make_quote(world, r)
    path = f"quotations/{q['id']}/accept"
    assert staff_post(world, "mgr_a1", r.pk, path, {"note": "x"}).status_code == 400          # not sent yet
    staff_post(world, "mgr_a1", r.pk, f"quotations/{q['id']}/send")
    token = token_of()
    assert staff_post(world, "mgr_a1", r.pk, path, {}).status_code == 400                      # note required
    assert staff_post(world, "cashier_a1", r.pk, path, {"note": "x"}).status_code == 403
    ok = staff_post(world, "mgr_a1", r.pk, path, {"note": "Accepted by phone 4pm, spoke to Dana"})
    assert ok.status_code == 200 and ok.data["status"] == "accepted" and ok.data["quotations"][0]["accepted_via"] == "recorded_by_staff"
    assert pub().get(f"{C}public/quotations/{token}/").status_code == 404
    assert staff_post(world, "mgr_a1", r.pk, path, {"note": "again"}).status_code == 400
    assert AuditLog.objects.filter(action="catering.quotation_accepted").get().metadata["via"] == "recorded_by_staff"


# =========================== payments & lifecycle ===============================================
def accepted_request(world, svc, branch="a1"):
    who = "mgr_a1" if branch == "a1" else "mgr_a2"
    r = new_req(world, svc, branch)
    q = make_quote(world, r, who=who)
    staff_post(world, who, r.pk, f"quotations/{q['id']}/send")
    staff_post(world, who, r.pk, f"quotations/{q['id']}/accept", {"note": "phone"})
    return r


def pay(world, r, who="mgr_a1", key="p1", **over):
    b = {"kind": "deposit", "amount": "1000.00", "method": "bank_transfer", "reference": "TX-1", "received_on": today().isoformat(), **over}
    return api(world, who).post(f"{C}requests/{r.pk}/payments/", b, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_payments_track_the_balance_and_never_exceed_it(world, svc):
    r = new_req(world, svc)
    assert pay(world, r).status_code == 400                                       # no accepted booking yet
    r = accepted_request(world, svc)
    ok = pay(world, r)
    assert ok.status_code == 201 and ok.data["balance"] == {"agreed_total": "3247.50", "paid": "1000.00", "balance": "2247.50", "currency": "USD"}
    assert pay(world, r, key="p1").data == ok.data and CateringPayment.unscoped.count() == 1      # idempotent replay
    assert pay(world, r, key="p2", amount="2247.51", kind="payment").status_code == 400            # cannot overpay
    assert pay(world, r, key="p3", amount="2247.50", kind="payment", method="cash").data["balance"]["balance"] == "0.00"
    assert pay(world, r, key="p4", amount="0.01", kind="payment").status_code == 400
    assert pay(world, r, key="p5", kind="refund", amount="5000").status_code == 400                # refund more than paid
    assert pay(world, r, key="p6", kind="refund", amount="200.00").data["balance"]["balance"] == "200.00"
    assert any("refund" in m["subject"].lower() for m in mails("dana@example.com"))
    assert [p["kind"] for p in api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").data["payments"]] == ["deposit", "payment", "refund"]
    assert AuditLog.objects.filter(action="catering.payment_recorded").count() == 3


def test_payment_validation_access_and_immutability(world, svc):
    r = accepted_request(world, svc)
    assert pay(world, r, key="a", received_on=(today() + timedelta(days=2)).isoformat()).status_code == 400
    assert pay(world, r, key="b", method="barter").status_code == 400
    assert pay(world, r, key="c", amount="-5").status_code == 400
    assert api(world, "mgr_a1").post(f"{C}requests/{r.pk}/payments/", {"kind": "deposit", "amount": "1", "method": "cash", "received_on": today().isoformat()}, format="json").status_code == 400  # no key
    for who in ("cashier_a1", "kitchen_a1", "cust_a"):
        assert pay(world, r, who=who, key=who).status_code == 403
    assert pay(world, r, who="mgr_a2", key="o").status_code == 404                                  # another branch's manager
    p = pay(world, r, key="ok") and CateringPayment.unscoped.get()
    with pytest.raises(PermissionError):
        p.delete()
    p.amount = Decimal("1")
    with pytest.raises(PermissionError):
        p.save()


def test_full_lifecycle_to_completion_and_cancellation_refund(world, svc):
    r = accepted_request(world, svc)
    pay(world, r)
    st = lambda to, note="": staff_post(world, "mgr_a1", r.pk, "status", {"status": to, "note": note})  # noqa: E731
    assert st("completed").status_code == 400
    assert st("in_progress").data["status"] == "in_progress"
    assert st("completed").data["status"] == "completed"
    assert any("Completed" in m["subject"] for m in mails("dana@example.com"))
    assert st("cancelled", "x").status_code == 400
    r2 = accepted_request(world, svc)
    pay(world, r2, key="r2")
    assert staff_post(world, "mgr_a1", r2.pk, "status", {"status": "cancelled", "note": "event called off"}).status_code == 200
    assert pay(world, r2, key="rf", kind="refund", amount="1000.00").status_code == 201          # refunds still allowed after cancellation
    assert pay(world, r2, key="np", kind="payment", amount="10").status_code == 400                # but no new payments


def test_admin_has_the_same_powers_across_branches(world, svc):
    r = accepted_request(world, svc, "a2")
    assert pay(world, r, who="admin_a", key="adm").status_code == 201
    assert staff_post(world, "admin_a", r.pk, "status", {"status": "in_progress"}).status_code == 200
    assert api(world, "mgr_a1").get(f"{C}requests/{r.pk}/").status_code == 404
