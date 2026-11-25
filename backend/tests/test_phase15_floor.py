import datetime
from datetime import timedelta

import pytest
from django.utils import timezone
from tests.conftest import TenantClient as APIClient

from apps.core.models import AuditLog
from apps.floor.models import FloorZone, Reservation
from apps.notifications.models import EmailLog
from apps.orders.models import Order
from apps.qrmenu.models import DiningTable
from apps.tenants.models import RestaurantSettings

from .conftest import client_for, host
from .test_phase5_orders import clean, shop  # noqa: F401
from .test_phase8_management import mk_order

FL = "/api/v1/floor/"


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def pub(slug="alpha"):
    return APIClient(HTTP_HOST=host(slug))


@pytest.fixture
def floor(world, shop, clean):  # noqa: F811
    t = {n: DiningTable.unscoped.create(restaurant=world["a"], branch=world["a1"], label=n, seats=s) for n, s in (("T1", 2), ("T2", 4), ("T6", 6))}
    DiningTable.unscoped.create(restaurant=world["a"], branch=world["a2"], label="B1", seats=4)
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(timezone="UTC")
    return t


def day(n=3):
    return (timezone.now() + timedelta(days=n)).date()


def book(world, party=2, hhmm="19:00", d=None, branch="a1", slug="alpha", **over):
    body = {"branch_id": world[branch].pk, "date": (d or day()).isoformat(), "time": hhmm, "party_size": party, "customer_name": "Dana Okoro", "customer_phone": "+23276123456",
            "customer_email": "dana@example.com", "accept_privacy": True, **over}
    return pub(slug).post(FL + "public/reservations/", body, format="json")


# ---------------- availability ----------------
def test_availability_lists_open_slots_and_shrinks_as_tables_fill(world, floor):
    r = pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": day().isoformat(), "party": 6})
    slots = r.json()["data"]["slots"]
    assert r.status_code == 200 and slots[0] == "09:00" and "19:00" in slots and "21:00" not in slots  # 90 min sitting must end by 22:00
    assert book(world, party=6, hhmm="19:00").status_code == 201
    after = pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": day().isoformat(), "party": 6}).json()["data"]["slots"]
    assert all(t not in after for t in ("18:00", "18:30", "19:00", "19:30", "20:00")) and "17:30" in after and "20:30" in after  # sittings may touch but not overlap
    two = pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": day().isoformat(), "party": 2}).json()["data"]["slots"]
    assert "19:00" in two  # smaller tables are still free


def test_closed_days_past_dates_and_bad_input(world, floor):
    world["a1"].operating_hours = {d: "10:00-22:00" for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")}
    world["a1"].save()
    sundays = [day(n) for n in range(1, 8) if day(n).weekday() == 6][0]
    assert pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": sundays.isoformat(), "party": 2}).json()["data"]["slots"] == []
    assert pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": (day(-2)).isoformat(), "party": 2}).json()["data"]["slots"] == []
    assert pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": "nope", "party": 2}).status_code == 400
    assert pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": day().isoformat(), "party": 99}).status_code == 400
    assert pub().get(FL + "public/availability/", {"branch": world["b1"].pk, "date": day().isoformat(), "party": 2}).status_code == 404  # other restaurant's branch


def test_slots_follow_the_restaurant_time_zone(world, floor):
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(timezone="Pacific/Auckland")
    r = book(world, hhmm="19:00")
    assert r.status_code == 201
    res = Reservation.unscoped.get()
    assert res.starts_at.astimezone(datetime.timezone.utc).hour != 19  # stored as UTC, shown in local time
    assert r.json()["data"]["local_time"] == "19:00"


# ---------------- public booking ----------------
def test_public_booking_assigns_the_smallest_fitting_table_and_emails(world, floor):
    r = book(world, party=3)
    assert r.status_code == 201, r.content
    d = r.json()["data"]
    assert d["reference"] == "RES-000001" and d["status"] == "confirmed" and d["table"] == "T2" and d["manage_token"] and "customer_phone" not in d
    assert EmailLog.objects.filter(template="reservation_confirmed").count() == 1
    res = Reservation.unscoped.get()
    assert res.token_hash and d["manage_token"] not in res.token_hash and len(res.token_hash) == 64
    assert book(world, party=2, hhmm="19:30").json()["data"]["table"] == "T1"


def test_double_booking_is_impossible(world, floor):
    assert book(world, party=6, hhmm="19:00").status_code == 201
    assert book(world, party=6, hhmm="19:00").status_code == 400  # same time, only one six-top
    assert book(world, party=6, hhmm="20:00").status_code == 400  # overlaps the 90-minute sitting
    assert book(world, party=5, hhmm="19:30").status_code == 400
    assert book(world, party=6, hhmm="20:30").status_code == 201  # back to back is fine
    # two small parties fit into T1, T2 and also the six-top
    for _ in range(3):
        assert book(world, party=2, hhmm="12:00").status_code == 201
    assert book(world, party=2, hhmm="12:00").status_code == 400
    assert Reservation.unscoped.filter(starts_at__hour=12).values("table_id").distinct().count() == 3


def test_booking_validation(world, floor):
    for over in ({"accept_privacy": False}, {"website": "http://spam"}, {"customer_phone": "abc"}, {"customer_name": ""}, {"party_size": 13}, {"party_size": 0}, {"time": "25:99"},
                {"hhmm": "08:00"}, {"hhmm": "21:30"}, {"branch_id": world["b1"].pk}):
        extra = dict(over)
        hh = extra.pop("hhmm", None)
        r = book(world, hhmm=hh or "19:00", **extra)
        assert r.status_code == 400, over
    soon = (timezone.now() + timedelta(minutes=10))
    assert book(world, d=soon.date(), hhmm=soon.strftime("%H:%M")).status_code == 400  # inside the lead time
    assert book(world, d=day(200)).status_code == 400  # too far ahead
    assert Reservation.unscoped.count() == 0


def test_reservations_can_be_switched_off(world, floor):
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(reservations_enabled=False)
    assert book(world).status_code == 400
    assert pub().get(FL + "public/availability/", {"branch": world["a1"].pk, "date": day().isoformat(), "party": 2}).json()["data"]["slots"] == []
    assert pub().get(FL + "public/options/").json()["data"]["enabled"] is False


def test_manual_confirmation_mode(world, floor):
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(reservation_auto_confirm=False)
    d = book(world).json()["data"]
    assert d["status"] == "requested"
    assert api(world, "cashier_a1").post(FL + f"reservations/{d['id']}/confirm/").json()["data"]["status"] == "confirmed"


# ---------------- guest self-service ----------------
def test_guest_can_view_and_cancel_with_the_private_token(world, floor):
    d = book(world, party=6).json()["data"]
    tok = d["manage_token"]
    g = pub().get(FL + f"public/reservations/{tok}/").json()["data"]
    assert g["reference"] == d["reference"] and "customer_email" not in g
    assert pub().get(FL + "public/reservations/wrong-token/").status_code == 404
    assert pub("bravo").get(FL + f"public/reservations/{tok}/").status_code == 404
    assert pub().post(FL + f"public/reservations/{tok}/").json()["data"]["status"] == "cancelled"
    assert pub().post(FL + f"public/reservations/{tok}/").status_code == 400
    assert book(world, party=6).status_code == 201  # the table is free again
    assert EmailLog.objects.filter(template="reservation_confirmed").count() == 2


def test_guest_cannot_cancel_after_the_start_time(world, floor):
    d = book(world).json()["data"]
    Reservation.unscoped.filter(pk=d["id"]).update(starts_at=timezone.now() - timedelta(minutes=5))
    assert pub().post(FL + f"public/reservations/{d['manage_token']}/").status_code == 400


# ---------------- staff ----------------
def test_staff_booking_list_scope_and_filters(world, floor):
    book(world, party=2, hhmm="12:00")
    book(world, party=2, hhmm="13:00", branch="a2")
    c1 = api(world, "cashier_a1").get(FL + "reservations/").json()["data"]
    assert c1["count"] == 1 and c1["results"][0]["customer_phone"]
    assert api(world, "admin_a").get(FL + "reservations/").json()["data"]["count"] == 2
    assert api(world, "admin_a").get(FL + "reservations/", {"date": day().isoformat(), "q": "dana"}).json()["data"]["count"] == 2
    assert api(world, "admin_a").get(FL + "reservations/", {"date": day(9).isoformat()}).json()["data"]["count"] == 0
    assert api(world, "admin_b", "bravo").get(FL + "reservations/").json()["data"]["count"] == 0
    for who in ("cust_a", "kitchen_a1", "delivery_a1"):
        assert api(world, who).get(FL + "reservations/").status_code == 403
    assert api(world, "cashier_a1").get(FL + f"reservations/{Reservation.unscoped.filter(branch=world['a2']).first().pk}/").status_code == 404


def test_staff_phone_booking_with_chosen_table_and_updates(world, floor):
    c = api(world, "cashier_a1")
    body = {"branch_id": world["a1"].pk, "date": day().isoformat(), "time": "18:00", "party_size": 2, "customer_name": "Walk-in", "customer_phone": "+23277000000", "table_id": floor["T6"].pk}
    r = c.post(FL + "reservations/", body, format="json")
    assert r.status_code == 201 and r.json()["data"]["table"] == "T6" and r.json()["data"]["source"] == "staff"
    rid = r.json()["data"]["id"]
    assert c.post(FL + "reservations/", {**body, "customer_name": "Other"}, format="json").status_code == 400  # T6 taken at that time
    assert c.post(FL + "reservations/", {**body, "branch_id": world["a2"].pk, "table_id": floor["T6"].pk}, format="json").status_code == 404
    u = c.patch(FL + f"reservations/{rid}/", {"time": "20:00", "party_size": 5, "notes": "Window seat"}, format="json")
    assert u.status_code == 200 and u.json()["data"]["local_time"] == "20:00" and u.json()["data"]["party_size"] == 5
    assert c.patch(FL + f"reservations/{rid}/", {"party_size": 8}, format="json").status_code == 400  # no table seats eight
    assert c.patch(FL + f"reservations/{rid}/", {"time": "23:00"}, format="json").status_code == 400  # closed
    assert AuditLog.objects.filter(action__in=["reservation.created", "reservation.updated"]).count() >= 2


def test_reservation_lifecycle_and_rules(world, floor):
    c = api(world, "cashier_a1")
    rid = book(world, hhmm="12:00").json()["data"]["id"]
    assert c.post(FL + f"reservations/{rid}/complete/").status_code == 400  # not seated
    assert c.post(FL + f"reservations/{rid}/no-show/").status_code == 400  # before the booking time
    assert c.post(FL + f"reservations/{rid}/cancel/", {"reason": ""}, format="json").status_code == 400
    assert c.post(FL + f"reservations/{rid}/seat/").json()["data"]["status"] == "seated"
    assert c.patch(FL + f"reservations/{rid}/", {"notes": "x"}, format="json").status_code == 400  # no edits once seated
    assert c.post(FL + f"reservations/{rid}/complete/").json()["data"]["status"] == "completed"
    assert c.post(FL + f"reservations/{rid}/seat/").status_code == 400
    r2 = book(world, hhmm="13:00").json()["data"]["id"]
    Reservation.unscoped.filter(pk=r2).update(starts_at=timezone.now() - timedelta(minutes=20))
    assert c.post(FL + f"reservations/{r2}/no-show/").json()["data"]["status"] == "no_show"
    r3 = book(world, hhmm="14:00").json()["data"]["id"]
    assert c.post(FL + f"reservations/{r3}/cancel/", {"reason": "Guest called"}, format="json").json()["data"]["status"] == "cancelled"
    assert EmailLog.objects.filter(template="reservation_cancelled").count() == 1
    assert c.post(FL + f"reservations/{r3}/explode/").status_code == 404
    with pytest.raises(PermissionError):
        Reservation.unscoped.get(pk=r3).delete()


def test_staff_cannot_touch_other_restaurants_or_branches(world, floor):
    rid = book(world, hhmm="12:00").json()["data"]["id"]
    for call in (lambda c: c.post(FL + f"reservations/{rid}/seat/"), lambda c: c.patch(FL + f"reservations/{rid}/", {"notes": "x"}, format="json"), lambda c: c.get(FL + f"reservations/{rid}/")):
        assert call(api(world, "cashier_a2")).status_code == 404
        assert call(api(world, "admin_b", "bravo")).status_code == 404


# ---------------- floor board, zones and layout ----------------
def test_floor_board_states(world, floor):
    c = api(world, "cashier_a1")
    z = api(world, "mgr_a1").post(FL + "zones/", {"name": "Terrace", "branch_id": world["a1"].pk, "sort_order": 1}, format="json").json()["data"]["id"]
    api(world, "mgr_a1").patch(FL + f"tables/{floor['T2'].pk}/layout/", {"zone_id": z, "pos_x": 20, "pos_y": 40, "shape": "round"}, format="json")
    seated = book(world, party=6, hhmm="12:00").json()["data"]["id"]
    Reservation.unscoped.filter(pk=seated).update(starts_at=timezone.now() - timedelta(minutes=10))
    c.post(FL + f"reservations/{seated}/seat/")
    soon = book(world, party=2, hhmm="12:00").json()["data"]["id"]
    Reservation.unscoped.filter(pk=soon).update(starts_at=timezone.now() + timedelta(minutes=30), table=floor["T1"])
    o, _ = mk_order(world, world["a1"], "20.00", status="confirmed")
    Order.unscoped.filter(pk=o.pk).update(table=floor["T2"])
    board = c.get(FL + "status/").json()["data"]
    by = {t["label"]: t for zn in board["zones"] for t in zn["tables"]}
    assert by["T6"]["state"] == "occupied" and by["T6"]["occupied_by"]["party"] == 6
    assert by["T1"]["state"] == "reserved" and by["T1"]["next_reservation"]["party"] == 2
    assert by["T2"]["state"] == "occupied" and by["T2"]["occupied_by"]["order"] == o.number
    assert board["counts"] == {"free": 0, "reserved": 1, "occupied": 2}
    assert {zn["zone"] for zn in board["zones"]} == {"Terrace", "Unassigned"} and by["T2"]["shape"] == "round" and by["T2"]["x"] == 20
    assert api(world, "mgr_a1").get(FL + "status/", {"branch": world["a2"].pk}).status_code == 404


def test_zone_and_layout_permissions_and_validation(world, floor):
    m, cash = api(world, "mgr_a1"), api(world, "cashier_a1")
    assert cash.post(FL + "zones/", {"name": "Bar", "branch_id": world["a1"].pk}, format="json").status_code == 403
    assert cash.patch(FL + f"tables/{floor['T1'].pk}/layout/", {"pos_x": 5}, format="json").status_code == 403
    z = m.post(FL + "zones/", {"name": "Bar", "branch_id": world["a1"].pk}, format="json").json()["data"]["id"]
    assert m.post(FL + "zones/", {"name": "bar", "branch_id": world["a1"].pk}, format="json").status_code == 400
    assert m.post(FL + "zones/", {"name": "X", "branch_id": world["a2"].pk}, format="json").status_code == 404
    assert m.patch(FL + f"zones/{z}/", {"name": "Bar area", "is_active": False}, format="json").json()["data"]["name"] == "Bar area"
    assert m.delete(FL + f"zones/{z}/").status_code == 405
    for bad in ({"pos_x": 101}, {"shape": "triangle"}, {"seats": 0}, {"zone_id": 99999}):
        assert m.patch(FL + f"tables/{floor['T1'].pk}/layout/", bad, format="json").status_code == 400, bad
    other = FloorZone.unscoped.create(restaurant=world["a"], branch=world["a2"], name="Other")
    assert m.patch(FL + f"tables/{floor['T1'].pk}/layout/", {"zone_id": other.pk}, format="json").status_code == 400  # zone of another branch
    assert api(world, "mgr_a1").patch(FL + f"tables/{DiningTable.unscoped.filter(branch=world['a2']).first().pk}/layout/", {"pos_x": 1}, format="json").status_code == 404
    assert api(world, "admin_b", "bravo").get(FL + "zones/").json()["data"] == []
