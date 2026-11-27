"""The page builder: who may design which website, what is accepted, and what visitors get."""
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.website.models import PageDesign

from .conftest import TenantClient, client_for, host

B = "/api/v1/website/builder/"


def block(**over):
    return {"layout": "cards", "title": "Why **us**", "items": [{"title": "Fresh", "text": "Daily", "button_label": "Menu", "button_link": "/menu"}], **over}


def save(user, slug, page="about", **body):
    return client_for(user, slug).put(f"{B}pages/{page}/", body, format="json")


def public(slug):
    return TenantClient(HTTP_HOST=host(slug)).get("/api/v1/website/public/pages/").data["pages"]


def upload(user, slug, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    buf = BytesIO()
    Image.new("RGB", (40, 30), "navy").save(buf, "PNG")
    return client_for(user, slug).post(B + "images/", {"image": SimpleUploadedFile("a.png", buf.getvalue(), content_type="image/png")}, format="multipart")


def test_admin_builds_a_page_and_only_visible_sections_are_public(world, tmp_path, settings):
    pic = upload(world["admin_a"], "alpha", tmp_path, settings)
    assert pic.status_code == 201
    r = save(world["admin_a"], "alpha", hero={"title": "Our story", "model": "burger", "image": pic.data["id"]},
             blocks=[block(), block(layout="accordion", visible=False, title="Hidden")])
    assert r.status_code == 200 and r.data["hero"]["image_url"]
    page = public("alpha")["about"]
    assert [b["title"] for b in page["blocks"]] == ["Why **us**"] and page["hero"]["model"] == "burger"
    assert public("bravo") == {} and public(None) == {}
    assert save(world["admin_a"], "alpha", blocks=[]).status_code == 200 and PageDesign.objects.count() == 1


def test_platform_pages_are_separate(world):
    assert save(world["platform"], None, "features", blocks=[block(button_link="/contact")]).status_code == 200
    assert "features" in public(None) and public("alpha") == {}
    assert save(world["platform"], None, "menu", blocks=[]).status_code == 404  # not a platform page


def test_only_the_right_administrator_may_design(world):
    for user, slug in ((world["mgr_a1"], "alpha"), (world["cashier_a1"], "alpha"), (world["cust_a"], "alpha"), (world["admin_b"], "alpha"), (world["admin_a"], None)):
        assert save(user, slug, blocks=[block()]).status_code == 403
        assert client_for(user, slug).get(B).status_code == 403
    assert not PageDesign.objects.exists()


@pytest.mark.parametrize("bad", [{"button_link": "javascript:alert(1)"}, {"button_link": "//evil.example"}, {"button_link": "http://insecure.example"},
                                 {"layout": "iframe"}, {"columns": 9}, {"title": "x" * 500}, {"model": "rocket"}, {"image": 999},
                                 {"items": [{"button_link": "data:text/html,x"}]}, {"items": [{}] * 30}])
def test_unsafe_or_unknown_content_is_refused(world, bad):
    assert save(world["admin_a"], "alpha", blocks=[block(**bad)]).status_code == 400


def test_a_picture_of_another_restaurant_cannot_be_used(world, tmp_path, settings):
    other = upload(world["admin_b"], "bravo", tmp_path, settings).data["id"]
    assert save(world["admin_a"], "alpha", blocks=[block(image=other)]).status_code == 400
