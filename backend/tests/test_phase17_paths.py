"""Restaurants are addressed by path (https://domain/<slug>/...), never by subdomain."""
from rest_framework.test import APIClient as Raw

from apps.tenants.models import RESERVED_SLUGS, Restaurant
from tests.conftest import PW


def platform():
    return Raw(HTTP_HOST="platform.test")


def test_slug_in_path_selects_the_restaurant(world):
    r = platform().get("/alpha/api/v1/restaurants/current/")
    assert r.status_code == 200 and r.json()["data"]["slug"] == "alpha"
    assert platform().get("/bravo/api/v1/restaurants/current/").json()["data"]["slug"] == "bravo"


def test_unknown_slug_and_wildcard_subdomains_do_not_resolve(world):
    assert platform().get("/nope/api/v1/restaurants/current/").status_code == 404
    sub = Raw(HTTP_HOST="alpha.platform.test").get("/api/v1/restaurants/current/")
    assert sub.status_code == 404 and sub.json()["error"]["code"] == "unknown_host"  # no wildcard-domain routing


def test_platform_paths_are_never_taken_for_a_restaurant(world):
    for p in ("/api/v1/platform/public/plans/", "/healthz"):
        assert platform().get(p).status_code == 200
    assert platform().get("/api/v1/restaurants/current/").status_code in (400, 404)  # platform host without a slug: no tenant


def test_reserved_words_cannot_be_used_as_slugs(db):
    from django.core.exceptions import ValidationError
    from apps.tenants.models import validate_slug

    for word in ("login", "admin", "api", "assets", "features", "ws"):
        assert word in RESERVED_SLUGS
        try:
            validate_slug(word)
        except ValidationError:
            continue
        raise AssertionError(word)


def test_a_token_for_one_restaurant_is_useless_in_another(world):
    tok = platform().post("/alpha/api/v1/auth/login/", {"email": "admin@a.com", "password": PW}, format="json").json()["data"]["access"]
    c = Raw(HTTP_HOST="platform.test", HTTP_AUTHORIZATION=f"Bearer {tok}")
    assert c.get("/alpha/api/v1/staff/members/").status_code == 200
    assert c.get("/bravo/api/v1/staff/members/").status_code in (401, 403, 404)


def test_public_url_and_suspension_follow_the_path(world):
    assert Restaurant.objects.get(slug="alpha").public_url == "http://platform.test/alpha"
    Restaurant.objects.filter(slug="alpha").update(status="suspended")
    assert platform().get("/alpha/api/v1/restaurants/current/").status_code == 403
    assert platform().get("/bravo/api/v1/restaurants/current/").status_code == 200


def test_site_pages_are_served_under_the_slug(world, settings, tmp_path):
    (tmp_path / "i.html").write_text("<html><head><!--runtime-config--></head><body>app</body></html>")
    settings.SPA_INDEX = tmp_path / "i.html"
    assert b"app" in platform().get("/alpha/menu").content
    assert b"app" in platform().get("/alpha").content
