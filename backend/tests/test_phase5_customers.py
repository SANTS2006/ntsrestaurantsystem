import io
import re

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from tests.conftest import TenantClient as APIClient

from apps.accounts.models import Membership, User
from apps.customers.models import CustomerAddress
from apps.notifications.providers import ConsoleProvider

from .conftest import PW, client_for, host

CU = "/api/v1/customers/"
NEW_PW = "Another-Str0ng-Pass9"


@pytest.fixture(autouse=True)
def clean(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    ConsoleProvider.outbox.clear()
    cache.clear()


def cust(world, who="cust_a", slug="alpha"):
    return client_for(world[who], slug)


def png(fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, fmt)
    return SimpleUploadedFile("a.png", buf.getvalue(), content_type="image/png")


ADDR = {"label": "Home", "line1": "12 Beach Rd", "city": "Freetown", "phone": "+23276000111"}


@pytest.mark.parametrize("who", ["admin_a", "mgr_a1", "cashier_a1"])
@pytest.mark.parametrize("url", ["me/", "addresses/", "dashboard/"])
def test_customer_endpoints_are_customer_only(world, who, url):
    assert client_for(world[who], "alpha").get(CU + url).status_code == 403


def test_customer_endpoints_require_login_and_membership_in_host_tenant(world):
    assert APIClient(HTTP_HOST=host("alpha")).get(CU + "me/").status_code == 401
    assert cust(world, slug="bravo").get(CU + "me/").status_code == 403  # alpha customer has no membership at bravo


def test_profile_read_update_and_validation(world):
    c = cust(world)
    assert c.get(CU + "me/").data["email"] == "cust@a.com"
    r = c.patch(CU + "me/", {"full_name": "Cara Customer", "phone": "+23276123456", "preferences": {"promotions": True}}, format="json")
    assert r.status_code == 200 and r.data["full_name"] == "Cara Customer" and r.data["preferences"] == {"order_emails": True, "promotions": True}
    assert c.patch(CU + "me/", {"phone": "call me"}, format="json").status_code == 400
    assert c.patch(CU + "me/", {"preferences": {"hack": True}}, format="json").status_code == 400
    assert c.patch(CU + "me/", {"full_name": ""}, format="json").status_code == 400
    c.patch(CU + "me/", {"email": "evil@x.com", "is_platform_admin": True, "role": "restaurant_admin"}, format="json")
    u = User.objects.get(pk=world["cust_a"].pk)
    assert u.email == "cust@a.com" and not u.is_platform_admin  # no mass assignment
    assert Membership.objects.get(user=u, restaurant=world["a"]).role == "customer"


def test_avatar_upload_validation_and_removal(world):
    c = cust(world)
    ok = c.post(CU + "me/avatar/", {"image": png()}, format="multipart")
    assert ok.status_code == 200 and "/avatars/" in ok.data["avatar"]
    assert c.post(CU + "me/avatar/", {"image": SimpleUploadedFile("a.png", b"junk", content_type="image/png")}, format="multipart").status_code == 400
    assert c.post(CU + "me/avatar/", {"image": png("GIF")}, format="multipart").status_code == 400
    assert c.delete(CU + "me/avatar/").data["avatar"] is None


def test_addresses_crud_defaults_and_limits(world):
    c = cust(world)
    a1 = c.post(CU + "addresses/", ADDR, format="json")
    assert a1.status_code == 201 and a1.data["is_default"] is True  # first one becomes default
    a2 = c.post(CU + "addresses/", {**ADDR, "label": "Work", "line1": "Office St", "is_default": True}, format="json")
    assert a2.data["is_default"] is True
    assert [a["is_default"] for a in c.get(CU + "addresses/").data] == [True, False] and c.get(CU + "addresses/").data[0]["label"] == "Work"
    assert c.patch(f"{CU}addresses/{a1.data['id']}/", {"city": "Bo"}, format="json").status_code == 200
    assert c.post(CU + "addresses/", {"line1": "x"}, format="json").status_code == 400  # city required
    assert c.post(CU + "addresses/", {**ADDR, "phone": "nope"}, format="json").status_code == 400
    assert c.delete(f"{CU}addresses/{a1.data['id']}/").status_code == 204
    for i in range(9):
        c.post(CU + "addresses/", {**ADDR, "label": f"L{i}"}, format="json")
    assert c.post(CU + "addresses/", ADDR, format="json").status_code == 400  # max 10


def test_addresses_are_private_to_their_owner_and_tenant(world):
    a = cust(world).post(CU + "addresses/", ADDR, format="json").data
    other = cust(world, "cust2_a")
    assert other.get(f"{CU}addresses/{a['id']}/").status_code == 404
    assert other.patch(f"{CU}addresses/{a['id']}/", {"city": "pwn"}, format="json").status_code == 404
    assert other.delete(f"{CU}addresses/{a['id']}/").status_code == 404
    assert other.get(CU + "addresses/").data == []
    assert CustomerAddress.unscoped.get(pk=a["id"]).city == "Freetown"
    mass = cust(world).post(CU + "addresses/", {**ADDR, "restaurant": world["b"].pk, "user": world["cust2_a"].pk}, format="json")
    obj = CustomerAddress.unscoped.get(pk=mass.data["id"])
    assert obj.restaurant_id == world["a"].pk and obj.user_id == world["cust_a"].pk


def code_to(email):
    mail = [m for m in ConsoleProvider.outbox if m["to"] == email][-1]
    return re.search(r"letter-spacing:6px[^>]*>([A-Z2-9]{6})<", mail["html"]).group(1)


def test_email_change_requires_password_and_code_from_new_mailbox(world):
    c = cust(world)
    old_token = APIClient(HTTP_HOST=host("alpha")).post("/api/v1/auth/login/", {"email": "cust@a.com", "password": PW}, format="json").data["data"]["access"]
    assert c.post(CU + "me/email-change/", {"new_email": "new@a.com", "password": "wrong-password-1"}, format="json").status_code == 400
    assert c.post(CU + "me/email-change/", {"new_email": "new@a.com", "password": PW}, format="json").status_code == 202
    assert [m["to"] for m in ConsoleProvider.outbox] == ["new@a.com"]  # nothing sent to the old address yet
    assert User.objects.get(pk=world["cust_a"].pk).email == "cust@a.com"  # unchanged until confirmed
    assert c.post(CU + "me/email-change/confirm/", {"code": "ZZZZZZ"}, format="json").status_code == 400
    r = c.post(CU + "me/email-change/confirm/", {"code": code_to("new@a.com")}, format="json")
    assert r.status_code == 200 and "access" in r.data["data"]
    u = User.objects.get(pk=world["cust_a"].pk)
    assert u.email == "new@a.com" and u.email_verified
    assert [m["to"] for m in ConsoleProvider.outbox][-1] == "cust@a.com"  # security notice to the OLD address
    stale = APIClient(HTTP_HOST=host("alpha"))
    stale.credentials(HTTP_AUTHORIZATION=f"Bearer {old_token}")
    assert stale.get(CU + "me/").status_code == 401  # tokens issued before the change are revoked
    login = APIClient(HTTP_HOST=host("alpha")).post("/api/v1/auth/login/", {"email": "new@a.com", "password": PW}, format="json")
    assert login.status_code == 200


def test_email_change_to_taken_address_is_indistinguishable_and_never_applied(world):
    c = cust(world)
    free = c.post(CU + "me/email-change/", {"new_email": "free@a.com", "password": PW}, format="json")
    ConsoleProvider.outbox.clear()
    cache.clear()
    taken = c.post(CU + "me/email-change/", {"new_email": "cust2@a.com", "password": PW}, format="json")
    assert free.status_code == taken.status_code == 202 and free.data == taken.data
    assert ConsoleProvider.outbox == []
    assert c.post(CU + "me/email-change/confirm/", {"code": "AAAAAA"}, format="json").status_code == 400
    assert User.objects.get(pk=world["cust_a"].pk).email == "cust@a.com"


def test_email_change_code_is_single_use_and_attempt_limited(world):
    c = cust(world)
    c.post(CU + "me/email-change/", {"new_email": "new@a.com", "password": PW}, format="json")
    code = code_to("new@a.com")
    for _ in range(5):
        c.post(CU + "me/email-change/confirm/", {"code": "AAAAAA"}, format="json")
    assert c.post(CU + "me/email-change/confirm/", {"code": code}, format="json").status_code == 400


def test_empty_dashboard(world):
    d = cust(world).get(CU + "dashboard/").data
    assert (d["total_orders"], d["current_orders"], d["completed_orders"], d["cancelled_orders"]) == (0, 0, 0, 0)
    assert d["recent_orders"] == [] and d["recent_activity"] == []
