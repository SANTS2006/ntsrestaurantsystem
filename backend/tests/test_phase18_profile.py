"""Waitress role, staff e-mail correction, own profile and picture, in-app notifications."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import Membership, Role, User
from apps.notifications.models import Notification
from apps.notifications.providers import ConsoleProvider

from .conftest import PW, client_for
from .test_phase5_orders import checkout, clean, line, move, shop  # noqa: F401

S = "/api/v1/staff/members/"
A = "/api/v1/auth/"
N = "/api/v1/notifications/"


def png(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")


def member(world, who):
    return Membership.objects.get(user=world[who], restaurant=world["a"])


# ------------------------------------------------------------------ waitress
def test_waitress_is_a_separate_role_from_waiter(world):
    assert Role.WAITER.label == "Waiter" and Role.WAITRESS.label == "Waitress"
    a = client_for(world["admin_a"], "alpha")
    m = member(world, "cashier_a1")
    r = a.patch(f"{S}{m.pk}/", {"role": "waitress"}, format="json")
    assert r.status_code == 200 and r.data["role"] == "waitress"
    r = a.patch(f"{S}{m.pk}/", {"role": "waiter"}, format="json")
    assert r.data["role"] == "waiter"


# ------------------------------------------------------------------ staff e-mail correction
def test_manager_can_correct_a_staff_email_and_sessions_end(world, clean):  # noqa: F811
    cashier = world["cashier_a1"]
    m = member(world, "cashier_a1")
    old_version = cashier.token_version
    r = client_for(world["admin_a"], "alpha").patch(f"{S}{m.pk}/", {"email": "Right.Address@A.com"}, format="json")
    assert r.status_code == 200 and r.data["email"] == "right.address@a.com"
    cashier.refresh_from_db()
    assert cashier.email == "right.address@a.com" and not cashier.email_verified and cashier.token_version == old_version + 1
    assert any(o["to"] == "right.address@a.com" for o in ConsoleProvider.outbox)  # the new mailbox must prove itself
    assert any(o["to"] == "cash1@a.com" for o in ConsoleProvider.outbox)          # the old one is told


def test_staff_email_change_is_refused_for_duplicates_and_shared_accounts(world):
    a = client_for(world["admin_a"], "alpha")
    m = member(world, "cashier_a1")
    dup = a.patch(f"{S}{m.pk}/", {"email": "mgr1@a.com"}, format="json")
    assert dup.status_code == 400 and "email" in str(dup.data)
    Membership.objects.create(user=world["cashier_a1"], restaurant=world["b"], role=Role.CASHIER)
    assert a.patch(f"{S}{m.pk}/", {"email": "someone@new.com"}, format="json").status_code == 400
    # a manager cannot touch someone above them
    assert client_for(world["mgr_a1"], "alpha").patch(f"{S}{member(world, 'admin_a').pk}/", {"email": "x@y.com"}, format="json").status_code in (403, 404, 400)


def test_pending_invitation_is_resent_to_the_corrected_address(world, clean):  # noqa: F811
    u = User.objects.create_user("typo@a.cmo", None, full_name="New Cook")
    m = Membership.objects.create(user=u, restaurant=world["a"], role=Role.KITCHEN)
    m.branches.set([world["a1"]])
    r = client_for(world["admin_a"], "alpha").patch(f"{S}{m.pk}/", {"email": "cook@a.com"}, format="json")
    assert r.status_code == 200
    assert any(o["to"] == "cook@a.com" and "invited" in o["subject"] for o in ConsoleProvider.outbox)


# ------------------------------------------------------------------ own profile
def test_everyone_can_edit_their_own_profile_and_picture(world):
    for who, slug in (("mgr_a1", "alpha"), ("cust_a", "alpha"), ("platform", None)):
        c = client_for(world[who], slug)
        assert c.patch(A + "profile/", {"full_name": "New Name", "phone": "+23276000111"}, format="json").status_code == 200
        r = c.post(A + "profile/avatar/", {"image": png()}, format="multipart")
        assert r.status_code == 200 and r.json()["data"]["avatar"], who
        assert c.get(A + "me/").json()["data"]["avatar"]
        first = User.objects.get(pk=world[who].pk).avatar.name
        c.post(A + "profile/avatar/", {"image": png((10, 90, 200))}, format="multipart")  # replace
        assert User.objects.get(pk=world[who].pk).avatar.name != first
        assert c.delete(A + "profile/avatar/").json()["data"]["avatar"] is None
    assert User.objects.get(pk=world["mgr_a1"].pk).full_name == "New Name"


def test_avatar_must_be_a_real_image(world):
    c = client_for(world["mgr_a1"], "alpha")
    bad = c.post(A + "profile/avatar/", {"image": SimpleUploadedFile("x.png", b"<script>alert(1)</script>", content_type="image/png")}, format="multipart")
    assert bad.status_code == 400


def test_email_change_needs_password_and_a_code_from_the_new_mailbox(world, clean):  # noqa: F811
    c = client_for(world["mgr_a1"], "alpha")
    assert c.post(A + "profile/email/", {"new_email": "fresh@a.com", "password": "wrong"}, format="json").status_code == 400
    assert c.post(A + "profile/email/", {"new_email": "fresh@a.com", "password": PW}, format="json").status_code == 202
    mail = [o for o in ConsoleProvider.outbox if o["to"] == "fresh@a.com"][-1]
    import re

    code = re.search(r"[A-Z2-9]{6}", mail["html"].split("verification")[-1] if False else re.sub(r"<[^>]+>", " ", mail["html"]).split("address.")[-1]).group(0)
    assert c.post(A + "profile/email/confirm/", {"code": "WRONG1"}, format="json").status_code == 400
    ok = c.post(A + "profile/email/confirm/", {"code": code}, format="json")
    assert ok.status_code == 200 and "access" in ok.json()["data"]
    assert User.objects.get(pk=world["mgr_a1"].pk).email == "fresh@a.com"


# ------------------------------------------------------------------ notifications
def test_order_events_reach_the_right_people_and_only_them(world, shop, clean):  # noqa: F811
    o = checkout(world, [line(shop["rice"], 1)], key="n1").data
    cashier_feed = client_for(world["cashier_a1"], "alpha").get(N).json()["data"]
    assert any(i["kind"] == "order_new" and o["number"] in i["title"] for i in cashier_feed["items"])
    assert not Notification.objects.filter(user=world["cashier_a2"]).exists()      # another branch hears nothing
    assert not Notification.objects.filter(user=world["admin_b"]).exists()         # another restaurant hears nothing
    for who, to in [("cashier_a1", "confirmed"), ("cashier_a1", "received"), ("kitchen_a1", "preparing"), ("kitchen_a1", "ready_for_pickup")]:
        assert move(world, who, o["id"], to).status_code == 200
    mine = client_for(world["cust_a"], "alpha").get(N).json()["data"]
    ready = [i for i in mine["items"] if i["kind"] == "order_ready"]
    assert ready and "ready for pickup" in ready[0]["title"] and mine["unread"] >= 1
    assert any(i["kind"] == "order_ready" for i in client_for(world["cashier_a1"], "alpha").get(N).json()["data"]["items"])


def test_notifications_are_private_and_can_be_marked_read(world, shop, clean):  # noqa: F811
    checkout(world, [line(shop["rice"], 1)], key="n2")
    c = client_for(world["cashier_a1"], "alpha")
    feed = c.get(N).json()["data"]
    assert feed["unread"] >= 1
    first = feed["items"][0]["id"]
    # another user cannot read or mark mine
    other = client_for(world["cashier_a2"], "alpha")
    assert other.get(N).json()["data"]["items"] == []
    other.post(N + "read/", {"ids": [first]}, format="json")
    assert c.get(N).json()["data"]["unread"] == feed["unread"]
    assert c.post(N + "read/", {"ids": [first]}, format="json").json()["data"]["unread"] == feed["unread"] - 1
    assert c.post(N + "read/", {}, format="json").json()["data"]["unread"] == 0
    after = c.get(N, {"after": str(first)}).json()["data"]["items"]
    assert all(i["id"] > first for i in after)
    c.post(N + "clear/", {}, format="json")
    assert Notification.objects.filter(user=world["cashier_a1"], read_at__isnull=False).count() == 0
    assert client_for(world["cashier_a1"]).get(N).status_code in (200, 401, 403)


def test_anonymous_cannot_read_notifications(world):
    from rest_framework.test import APIClient

    assert APIClient(HTTP_HOST="platform.test").get("/alpha" + N).status_code == 401


# ------------------------------------------------------------------ deactivation / activation emails
def test_people_are_emailed_when_their_account_is_deactivated_and_activated(world, clean):  # noqa: F811
    a = client_for(world["admin_a"], "alpha")
    m = member(world, "kitchen_a1")
    assert a.post(f"{S}{m.pk}/deactivate/", {"reason": "left"}, format="json").status_code == 200
    sent = [o for o in ConsoleProvider.outbox if o["to"] == "kitchen1@a.com"]
    assert len(sent) == 1 and "deactivated" in sent[0]["subject"] and "left" not in sent[0]["html"]  # the internal reason is not shared
    assert a.post(f"{S}{m.pk}/deactivate/", {}, format="json").status_code == 200  # already inactive: no second email
    assert len([o for o in ConsoleProvider.outbox if o["to"] == "kitchen1@a.com"]) == 1
    assert a.post(f"{S}{m.pk}/activate/", {}, format="json").status_code == 200
    sent = [o for o in ConsoleProvider.outbox if o["to"] == "kitchen1@a.com"]
    assert len(sent) == 2 and "activated" in sent[1]["subject"] and "/alpha/login" in sent[1]["html"]
