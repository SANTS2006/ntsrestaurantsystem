"""Website contact forms, the team inbox, and the platform website's editable texts and pictures."""
import pytest
from django.core.cache import cache

from apps.core.models import AuditLog
from apps.notifications.models import Notification
from apps.notifications.providers import ConsoleProvider
from apps.website.content import DEFAULTS, plain
from apps.website.models import ContactActivity, ContactMessage, PlatformContent

from .conftest import TenantClient, client_for, host

W = "/api/v1/website/"


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()
    ConsoleProvider.outbox.clear()


def form(**over):
    return {"name": "Mary Kamara", "email": "mary@example.com", "phone": "+232 76 123456", "subject": "Opening hours",
            "message": "Are you open on public holidays?", "topic": "general", "consent": True, **over}


def send(slug=None, **over):
    return TenantClient(HTTP_HOST=host(slug)).post(W + "public/contact/", form(**over), format="json")


def mail_to(address):
    return [m for m in ConsoleProvider.outbox if m["to"] == address]


def test_message_is_saved_for_the_right_website_and_the_team_is_told(world, django_capture_on_commit_callbacks):
    world["a"].contact_email = "hello@alpha.test"
    world["a"].save()
    with django_capture_on_commit_callbacks(execute=True):
        r = send("alpha", branch_id=world["a1"].pk)
    assert r.status_code == 201 and r.data["reference"].startswith("MSG-")
    m = ContactMessage.objects.get()
    assert m.restaurant == world["a"] and m.branch == world["a1"] and m.status == "new" and m.consented_at
    told = set(Notification.objects.filter(kind="contact_message").values_list("user__email", flat=True))
    assert told == {"admin@a.com", "mgr1@a.com"}  # not the other branch's manager, not the other restaurant
    assert mail_to("hello@alpha.test")


def test_platform_message_has_no_restaurant_and_goes_to_platform_admins(world):
    assert send(business_name="Mary's Kitchen", topic="sales").status_code == 201
    m = ContactMessage.objects.get()
    assert m.restaurant is None and m.business_name == "Mary's Kitchen"
    assert set(Notification.objects.values_list("user__email", flat=True)) == {"root@x.com"}


@pytest.mark.parametrize("bad", [{"email": "nope"}, {"consent": False}, {"message": "short"}, {"name": ""}, {"subject": "a"},
                                 {"phone": "call me"}, {"preferred_contact": "phone", "phone": ""}, {"topic": "hack"}])
def test_invalid_submissions_are_refused(world, bad):
    assert send("alpha", **bad).status_code == 400
    assert not ContactMessage.objects.exists()


def test_branch_of_another_restaurant_is_refused(world):
    assert send("alpha", branch_id=world["b1"].pk).status_code == 400
    assert send(None, branch_id=world["a1"].pk).status_code == 400


def test_honeypot_stores_nothing_and_a_repeat_is_not_duplicated(world):
    assert send("alpha", company_website="http://spam.example").status_code == 201
    assert not ContactMessage.objects.exists()
    first, again = send("alpha"), send("alpha")
    assert first.data["reference"] == again.data["reference"] and ContactMessage.objects.count() == 1


def test_form_is_rate_limited(world, monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "contact", "8/hour")  # the rate the real settings use
    codes = [send("alpha", subject=f"Question {i}").status_code for i in range(10)]
    assert codes[:8] == [201] * 8 and codes[-1] == 429


def test_inbox_is_isolated_by_restaurant_branch_and_role(world):
    send("alpha", branch_id=world["a2"].pk, subject="For branch two")
    send("alpha", subject="For everyone")
    send("bravo", subject="For bravo")
    send(None, subject="For the platform")

    def subjects(user, slug):
        r = client_for(user, slug).get(W + "messages/")
        return (r.status_code, sorted(x["subject"] for x in r.data["results"]) if r.status_code == 200 else None)

    assert subjects(world["admin_a"], "alpha") == (200, ["For branch two", "For everyone"])
    assert subjects(world["mgr_a1"], "alpha") == (200, ["For everyone"])
    assert subjects(world["platform"], None) == (200, ["For the platform"])
    for user, slug in ((world["cashier_a1"], "alpha"), (world["cust_a"], "alpha"), (world["admin_a"], None), (world["admin_b"], "alpha")):
        assert subjects(user, slug)[0] == 403
    other = ContactMessage.objects.get(subject="For bravo")
    assert client_for(world["admin_a"], "alpha").get(f"{W}messages/{other.pk}/").status_code == 404
    hidden = ContactMessage.objects.get(subject="For branch two")
    assert client_for(world["mgr_a1"], "alpha").post(f"{W}messages/{hidden.pk}/", {"action": "note", "text": "peek"}, format="json").status_code == 404


def test_reply_note_and_status_are_recorded_and_the_reply_is_emailed(world, django_capture_on_commit_callbacks):
    send("alpha")
    m = ContactMessage.objects.get()
    admin = client_for(world["admin_a"], "alpha")
    detail = admin.get(f"{W}messages/{m.pk}/").data
    assert detail["message"] == m.message and detail["phone"] == "+232 76 123456" and detail["activity"] == []

    assert admin.post(f"{W}messages/{m.pk}/", {"action": "note", "text": "Called, no answer"}, format="json").data["status"] == "in_progress"
    with django_capture_on_commit_callbacks(execute=True):
        r = admin.post(f"{W}messages/{m.pk}/", {"action": "reply", "text": "Yes <b>we are</b> open."}, format="json")
    assert r.status_code == 200 and r.data["status"] == "replied"
    sent = mail_to("mary@example.com")
    assert len(sent) == 1 and "&lt;b&gt;we are" in sent[0]["html"]
    again = admin.post(f"{W}messages/{m.pk}/", {"action": "reply", "text": "Yes <b>we are</b> open."}, format="json")
    assert again.status_code == 400
    assert admin.post(f"{W}messages/{m.pk}/", {"action": "status", "status": "closed"}, format="json").data["status"] == "closed"
    assert [a.kind for a in ContactActivity.objects.all()] == ["note", "reply", "status"]
    assert AuditLog.objects.filter(action__startswith="contact.").count() >= 4
    assert admin.delete(f"{W}messages/{m.pk}/").status_code == 405


def test_spam_is_hidden_by_default_and_cannot_be_replied_to(world):
    send("alpha")
    m = ContactMessage.objects.get()
    admin = client_for(world["admin_a"], "alpha")
    admin.post(f"{W}messages/{m.pk}/", {"action": "status", "status": "spam"}, format="json")
    assert admin.get(W + "messages/").data["results"] == []
    assert admin.get(W + "messages/", {"status": "spam"}).data["counts"]["spam"] == 1
    assert admin.post(f"{W}messages/{m.pk}/", {"action": "reply", "text": "Hello"}, format="json").status_code == 400


def test_notification_detail_shows_the_message(world):
    send(None)
    n = Notification.objects.get(user=world["platform"])
    data = client_for(world["platform"], None).get(f"/api/v1/notifications/{n.pk}/").data["data"]
    assert data["details"]["heading"].startswith("Website message") and n.link.startswith("/admin/messages?open=")


# ---- website content ----------------------------------------------------------------------------------------------
def public_content():
    return TenantClient(HTTP_HOST=host()).get(W + "public/content/").data


def test_public_content_has_the_defaults_until_edited(world):
    data = public_content()
    assert data["content"]["home"]["title"] == DEFAULTS["home"]["title"] and "privacy-policy" in data["draft_legal"]
    assert not PlatformContent.objects.exists()  # reading never writes


def test_platform_admin_edits_pages_and_the_website_shows_them(world, settings):
    admin = client_for(world["platform"], None)
    r = admin.patch(W + "content/", {"home": {"title": "Sell **more** food"},
                                     "faq": {"items": [{"q": "Is it good?", "a": "**Yes.**"}]},
                                     "legal": {"privacy-policy": [{"title": "Reviewed", "text": "Our real policy."}]},
                                     "contact": {"locations": [{"name": "Head office", "address": "1 Siaka Stevens Street, Freetown", "latitude": "8.4844", "longitude": "-13.2344"}]},
                                     "seo": {"about": {"title": "Our **story**", "text": "Who we are."}}}, format="json")
    assert r.status_code == 200
    data = public_content()
    assert data["content"]["home"]["title"] == "Sell **more** food" and data["content"]["home"]["lead"] == DEFAULTS["home"]["lead"]
    assert data["content"]["faq"]["items"] == [{"q": "Is it good?", "a": "**Yes.**"}]
    assert "privacy-policy" not in data["draft_legal"] and "cookie-policy" in data["draft_legal"]
    assert data["content"]["contact"]["locations"][0]["latitude"] == "8.4844"
    assert data["content"]["seo"]["about"]["title"] == "Our story"
    assert AuditLog.objects.filter(action="platform.website_content_updated").exists()

    from apps.core import seo_meta

    assert seo_meta._platform("about")["title"].startswith("Our story")

    assert admin.patch(W + "content/", {"home": None}, format="json").status_code == 200
    assert public_content()["content"]["home"]["title"] == DEFAULTS["home"]["title"]


@pytest.mark.parametrize("body", [{"nope": {}}, {"home": {"evil": "x"}}, {"home": {"title": 5}}, {"home": {"title": "x" * 900}},
                                  {"faq": {"items": [{"q": "", "a": "x"}]}}, {"faq": {"items": "x"}},
                                  {"contact": {"locations": [{"name": "A", "latitude": "999", "longitude": "1"}]}},
                                  {"legal": {"unknown-page": []}}])
def test_content_edits_are_validated(world, body):
    assert client_for(world["platform"], None).patch(W + "content/", body, format="json").status_code == 400


def test_only_the_platform_admin_on_the_platform_may_edit(world):
    for user, slug in ((world["admin_a"], None), (world["admin_a"], "alpha"), (world["platform"], "alpha")):
        assert client_for(user, slug).patch(W + "content/", {"home": {"title": "Hacked"}}, format="json").status_code == 403
        assert client_for(user, slug).delete(W + "content/images/home/").status_code == 403


def test_hero_picture_upload_replace_and_remove(world, settings, tmp_path):
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    settings.MEDIA_ROOT = tmp_path
    buf = BytesIO()
    Image.new("RGB", (60, 30), "navy").save(buf, "PNG")
    admin = client_for(world["platform"], None)
    r = admin.post(W + "content/images/home/", {"image": SimpleUploadedFile("a.png", buf.getvalue(), content_type="image/png")}, format="multipart")
    assert r.status_code == 200 and "home" in r.data["images"] and "home" in public_content()["images"]
    bad = admin.post(W + "content/images/home/", {"image": SimpleUploadedFile("a.png", b"<svg/>", content_type="image/png")}, format="multipart")
    assert bad.status_code == 400
    assert admin.post(W + "content/images/nowhere/", {}, format="multipart").status_code == 404
    assert "home" not in admin.delete(W + "content/images/home/").data["images"]


def test_plain_text_drops_the_bold_markers():
    assert plain("a **bold** word and a stray **") == "a bold word and a stray "
