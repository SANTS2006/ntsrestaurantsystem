import io
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from tests.conftest import TenantClient as APIClient

from apps.catalog.models import Category, Product, StockMovement
from apps.core.models import AuditLog

from .conftest import client_for, host

C = "/api/v1/catalog/"


@pytest.fixture(autouse=True)
def media(settings, tmp_path, db):
    settings.MEDIA_ROOT = tmp_path
    from django.core.cache import cache
    cache.clear()


def png(fmt="PNG", name="p.png"):
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), "blue").save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def admin(world, slug="alpha"):
    return client_for(world["admin_a" if slug == "alpha" else "admin_b"], slug)


def mk_category(world, name="Mains", slug="alpha"):
    r = admin(world, slug).post(C + "categories/", {"name": name}, format="json")
    assert r.status_code == 201, r.data
    return r.data["id"]


def mk_product(world, cat, slug="alpha", **over):
    body = {"category": cat, "name": "Jollof Rice", "base_price": "45.50", "description": "Spicy", **over}
    r = admin(world, slug).post(C + "products/", body, format="json")
    assert r.status_code == 201, r.data
    return r.data


def public(slug="alpha"):
    return APIClient(HTTP_HOST=host(slug))


# ---- access control ----------------------------------------------------------------------------
MANAGE = [("get", "categories/"), ("post", "categories/"), ("get", "products/"), ("post", "products/"),
          ("get", "services/"), ("post", "services/"), ("get", "gallery/"), ("get", "stock-movements/"),
          ("get", "site/"), ("patch", "site/")]


@pytest.mark.parametrize("who", ["cashier_a1", "cust_a"])
@pytest.mark.parametrize("method,url", MANAGE)
def test_cashier_and_customer_cannot_manage_catalog(world, who, method, url):
    assert getattr(client_for(world[who], "alpha"), method)(C + url, {}, format="json").status_code == 403


@pytest.mark.parametrize("method,url", MANAGE)
def test_anonymous_cannot_manage_catalog(world, method, url):
    assert getattr(public(), method)(C + url, {}, format="json").status_code == 401


def test_catalog_management_not_available_on_platform_host(world):
    assert client_for(world["platform"], None).get(C + "products/").status_code == 403


def test_manager_can_manage_products_but_not_site_content(world):
    m = client_for(world["mgr_a1"], "alpha")
    cat = m.post(C + "categories/", {"name": "Drinks"}, format="json")
    assert cat.status_code == 201
    assert m.post(C + "products/", {"category": cat.data["id"], "name": "Cola", "base_price": "3.00"}, format="json").status_code == 201
    assert m.patch(C + "site/", {"about_text": "x"}, format="json").status_code == 403
    assert admin(world).patch(C + "site/", {"about_text": "x"}, format="json").status_code == 200


# ---- tenant isolation --------------------------------------------------------------------------
def test_tenant_data_isolated_and_slugs_scoped_per_tenant(world):
    ca, cb = mk_category(world, slug="alpha"), mk_category(world, slug="bravo")
    pa, pb = mk_product(world, ca), mk_product(world, cb, slug="bravo")
    assert pa["slug"] == pb["slug"] == "jollof-rice"  # same slug allowed across tenants
    assert [p["id"] for p in admin(world).get(C + "products/").data["results"]] == [pa["id"]]
    a = admin(world)
    assert a.get(f"{C}products/{pb['id']}/").status_code == 404
    assert a.patch(f"{C}products/{pb['id']}/", {"name": "pwn"}, format="json").status_code == 404
    assert a.post(f"{C}products/{pb['id']}/archive/").status_code == 404
    assert a.post(f"{C}products/{pb['id']}/stock/", {"delta": 5, "reason": "restock"}, format="json").status_code == 404
    assert a.patch(f"{C}categories/{cb}/", {"name": "pwn"}, format="json").status_code == 404


def test_cannot_attach_product_to_other_tenants_category(world):
    cb = mk_category(world, slug="bravo")
    r = admin(world).post(C + "products/", {"category": cb, "name": "X", "base_price": "1.00"}, format="json")
    assert r.status_code == 400 and not Product.unscoped.filter(name="X").exists()


def test_restaurant_cannot_be_mass_assigned(world):
    ca = mk_category(world)
    r = admin(world).post(C + "products/", {"category": ca, "name": "Y", "base_price": "1", "restaurant": world["b"].pk}, format="json")
    assert Product.unscoped.get(pk=r.data["id"]).restaurant_id == world["a"].pk


def test_same_slug_collisions_get_suffix_within_tenant(world):
    ca = mk_category(world)
    assert [mk_product(world, ca)["slug"] for _ in range(2)] == ["jollof-rice", "jollof-rice-2"]


# ---- validation & nested options ---------------------------------------------------------------
@pytest.mark.parametrize("over", [{"base_price": "-1"}, {"base_price": "abc"}, {"offer_price": "50.00"},
                                  {"offer_price": "45.50"}, {"ingredients": "rice"}, {"name": ""}])
def test_product_validation(world, over):
    ca = mk_category(world)
    r = admin(world).post(C + "products/", {"category": ca, "name": "Z", "base_price": "10.00", **over}, format="json")
    assert r.status_code == 400


def test_variations_and_addons_create_update_remove(world):
    ca = mk_category(world)
    p = mk_product(world, ca, variations=[{"name": "Small", "price_delta": "0.00", "is_default": True},
                                          {"name": "Large", "price_delta": "10.00"}],
                   addons=[{"name": "Extra egg", "price": "2.50", "max_quantity": 3}])
    assert [v["name"] for v in p["variations"]] == ["Small", "Large"] and p["addons"][0]["price"] == "2.50"
    large = p["variations"][1]
    r = admin(world).patch(f"{C}products/{p['id']}/", {"variations": [{"id": large["id"], "name": "Large", "price_delta": "12.00"}],
                                                       "addons": []}, format="json")
    assert r.status_code == 200 and [(v["name"], v["price_delta"]) for v in r.data["variations"]] == [("Large", "12.00")]
    assert r.data["addons"] == []
    bad = admin(world).patch(f"{C}products/{p['id']}/", {"variations": [{"id": 999999, "name": "X", "price_delta": "1"}]}, format="json")
    assert bad.status_code == 400


def test_variation_rules(world):
    ca = mk_category(world)
    two_defaults = [{"name": "A", "price_delta": "0", "is_default": True}, {"name": "B", "price_delta": "1", "is_default": True}]
    dup = [{"name": "A", "price_delta": "0"}, {"name": "a", "price_delta": "1"}]
    neg = [{"name": "A", "price_delta": "-1"}]
    for variations in (two_defaults, dup, neg):
        r = admin(world).post(C + "products/", {"category": ca, "name": "V", "base_price": "5", "variations": variations}, format="json")
        assert r.status_code == 400


def test_money_is_exact_decimal(world):
    ca = mk_category(world)
    p = mk_product(world, ca, base_price="0.10")
    assert Product.unscoped.get(pk=p["id"]).base_price == Decimal("0.10") and p["base_price"] == "0.10"


# ---- archive, audit ----------------------------------------------------------------------------
def test_products_are_archived_not_deleted_and_hidden_publicly(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    assert admin(world).delete(f"{C}products/{p['id']}/").status_code == 405
    assert admin(world).post(f"{C}products/{p['id']}/archive/").data["is_archived"] is True
    assert admin(world).get(C + "products/").data["count"] == 0
    assert admin(world).get(C + "products/?archived=1").data["count"] == 1
    assert json.loads(public().get(C + "public/menu/").content)["data"] == []
    assert public().get(C + f"public/products/{p['slug']}/").status_code == 404
    admin(world).post(f"{C}products/{p['id']}/restore/")
    assert public().get(C + f"public/products/{p['slug']}/").status_code == 200


def test_price_and_availability_changes_are_audited_with_old_and_new(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    r = admin(world).patch(f"{C}products/{p['id']}/", {"base_price": "50.00", "is_available": False}, format="json")
    assert r.status_code == 200
    log = AuditLog.objects.filter(action="product.updated").latest("id")
    assert log.metadata["changes"]["base_price"] == ["45.50", "50.00"] and log.metadata["changes"]["is_available"] == [True, False]
    assert log.actor == world["admin_a"] and log.restaurant == world["a"]
    n = AuditLog.objects.count()
    admin(world).patch(f"{C}products/{p['id']}/", {"description": "same"}, format="json")
    admin(world).patch(f"{C}products/{p['id']}/", {"base_price": "50.00"}, format="json")  # no-op
    assert AuditLog.objects.filter(action="product.updated").count() == 1 and AuditLog.objects.count() == n


# ---- images ------------------------------------------------------------------------------------
def test_product_image_upload_validation_and_random_names(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    url = f"{C}products/{p['id']}/image/"
    ok = admin(world).post(url, {"image": png(name="../../evil name.png")}, format="multipart")
    assert ok.status_code == 200 and "/products/" in ok.data["image"] and "evil" not in ok.data["image"]
    assert admin(world).post(url, {"image": SimpleUploadedFile("a.png", b"junk", content_type="image/png")}, format="multipart").status_code == 400
    assert admin(world).post(url, {"image": SimpleUploadedFile("a.svg", b"<svg/>", content_type="image/svg+xml")}, format="multipart").status_code == 400
    assert admin(world).post(url, {"image": png("GIF", "a.gif")}, format="multipart").status_code == 400
    d = admin(world).delete(url)
    assert d.status_code == 200, (d.status_code, d.data)
    assert d.data["image"] is None


def test_cashier_cannot_upload_images(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    r = client_for(world["cashier_a1"], "alpha").post(f"{C}products/{p['id']}/image/", {"image": png()}, format="multipart")
    assert r.status_code == 403


# ---- inventory ---------------------------------------------------------------------------------
def test_stock_adjustment_ledger_rules_and_low_stock(world):
    ca = mk_category(world)
    p = mk_product(world, ca, track_inventory=True, low_stock_threshold=5)
    url = f"{C}products/{p['id']}/stock/"
    a = admin(world)
    assert a.post(url, {"delta": 10, "reason": "restock", "note": "delivery"}, format="json").data["stock_quantity"] == 10
    assert a.post(url, {"delta": -11, "reason": "waste"}, format="json").status_code == 400  # never negative
    assert a.post(url, {"delta": 0, "reason": "restock"}, format="json").status_code == 400
    assert a.post(url, {"delta": -1, "reason": "sale"}, format="json").status_code == 400  # sales come from the order flow
    assert a.post(url, {"delta": -6, "reason": "waste"}, format="json").data["stock_quantity"] == 4
    assert [x["id"] for x in a.get(C + "products/low-stock/").data] == [p["id"]]
    moves = a.get(C + f"stock-movements/?product={p['id']}").data["results"]
    assert [(m["delta"], m["quantity_after"]) for m in moves] == [(-6, 4), (10, 10)]
    m = StockMovement.unscoped.first()
    with pytest.raises(PermissionError):
        m.delete()
    assert AuditLog.objects.filter(action="inventory.adjusted").count() == 2
    # the stock figure cannot be written directly
    a.patch(f"{C}products/{p['id']}/", {"stock_quantity": 999}, format="json")
    assert Product.unscoped.get(pk=p["id"]).stock_quantity == 4


def test_stock_requires_tracking_and_manager_role(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    assert admin(world).post(f"{C}products/{p['id']}/stock/", {"delta": 1, "reason": "restock"}, format="json").status_code == 400
    assert client_for(world["cashier_a1"], "alpha").post(f"{C}products/{p['id']}/stock/", {"delta": 1, "reason": "restock"}, format="json").status_code == 403


def test_sold_out_flag_public_and_stock_numbers_hidden(world):
    ca = mk_category(world)
    mk_product(world, ca, track_inventory=True)
    item = json.loads(public().get(C + "public/menu/").content)["data"][0]["products"][0]
    assert item["sold_out"] is True and "stock_quantity" not in item and "track_inventory" not in item


# ---- public menu -------------------------------------------------------------------------------
def pub_menu(slug="alpha", **params):
    return json.loads(public(slug).get(C + "public/menu/", params).content)["data"]


def test_public_menu_shows_only_active_available_items_per_tenant(world):
    ca, drinks = mk_category(world, "Mains"), mk_category(world, "Drinks")
    mk_product(world, ca, name="Visible")
    mk_product(world, ca, name="Unavailable", is_available=False)
    mk_product(world, drinks, name="Cola")
    mk_product(world, mk_category(world, "Bravo Food", "bravo"), name="Bravo only", slug="bravo")
    admin(world).patch(f"{C}categories/{drinks}/", {"is_active": False}, format="json")
    menu = pub_menu()
    assert [(c["name"], [p["name"] for p in c["products"]]) for c in menu] == [("Mains", ["Visible"])]
    assert [p["name"] for c in pub_menu("bravo") for p in c["products"]] == ["Bravo only"]


def test_menu_search_and_category_filter(world):
    ca, dr = mk_category(world, "Mains"), mk_category(world, "Drinks")
    mk_product(world, ca, name="Fish stew")
    mk_product(world, dr, name="Orange juice")
    assert [p["name"] for c in pub_menu(q="fish") for p in c["products"]] == ["Fish stew"]
    assert [c["slug"] for c in pub_menu(category="drinks")] == ["drinks"]
    assert pub_menu(q="zzz") == []


def test_offers_use_effective_price_and_expire(world):
    ca = mk_category(world)
    p = mk_product(world, ca, offer_price="30.00", offer_label="Lunch deal")
    item = pub_menu()[0]["products"][0]
    assert (item["price"], item["regular_price"], item["on_offer"], item["offer_label"]) == ("30.00", "45.50", True, "Lunch deal")
    Product.unscoped.filter(pk=p["id"]).update(offer_ends_at=timezone.now() - timedelta(hours=1))
    from apps.catalog.cache import bump_menu
    bump_menu(world["a"].pk)
    item = pub_menu()[0]["products"][0]
    assert (item["price"], item["on_offer"], item["offer_label"]) == ("45.50", False, "")


def test_menu_cache_is_invalidated_on_change_and_isolated_per_tenant(world):
    ca = mk_category(world)
    p = mk_product(world, ca)
    assert pub_menu()[0]["products"][0]["price"] == "45.50"
    assert pub_menu("bravo") == []
    admin(world).patch(f"{C}products/{p['id']}/", {"base_price": "60.00"}, format="json")
    assert pub_menu()[0]["products"][0]["price"] == "60.00"  # visible immediately, not after TTL
    admin(world).patch(f"{C}products/{p['id']}/", {"is_available": False}, format="json")
    assert pub_menu() == []
    assert pub_menu("bravo") == []


def test_public_menu_query_count_is_constant(world, django_assert_max_num_queries):
    ca = mk_category(world)
    for i in range(12):
        mk_product(world, ca, name=f"Dish {i}", variations=[{"name": "S", "price_delta": "0"}], addons=[{"name": "E", "price": "1"}])
    from django.core.cache import cache
    cache.clear()
    with django_assert_max_num_queries(8):
        assert len(pub_menu()[0]["products"]) == 12


def test_public_endpoints_need_a_restaurant_host_and_respect_suspension(world):
    assert APIClient(HTTP_HOST=host()).get(C + "public/menu/").status_code == 404
    world["a"].status = "suspended"
    world["a"].save()
    assert public().get(C + "public/menu/").status_code == 403


# ---- site content, policies, services, gallery, SEO --------------------------------------------
def test_public_site_content_branches_and_policies(world):
    a = admin(world)
    r = a.patch(C + "site/", {"hero_title": "Taste the coast", "about_text": "Family run", "faqs": [{"q": "Open?", "a": "Daily"}],
                              "policies": {"privacy-policy": "Custom privacy text"}, "primary_color": "#112233"}, format="json")
    assert r.status_code == 200
    site = json.loads(public().get(C + "public/site/").content)["data"]
    assert site["hero_title"] == "Taste the coast" and site["restaurant"]["primary_color"] == "#112233"
    assert [b["code"] if "code" in b else b["name"] for b in site["branches"]] == ["A One", "A Two"]
    assert json.loads(public().get(C + "public/policies/privacy-policy/").content)["data"]["text"] == "Custom privacy text"
    default = json.loads(public().get(C + "public/policies/terms-of-use/").content)["data"]["text"]
    assert "Alpha" in default
    assert public().get(C + "public/policies/nope/").status_code == 404
    assert "Taste the coast" not in json.dumps(json.loads(public("bravo").get(C + "public/site/").content))


def test_suspended_branches_hidden_from_public_site(world):
    world["a2"].status = "suspended"
    world["a2"].save()
    assert [b["name"] for b in json.loads(public().get(C + "public/site/").content)["data"]["branches"]] == ["A One"]


@pytest.mark.parametrize("body", [{"faqs": [{"q": "only q"}]}, {"policies": {"made-up": "x"}}, {"primary_color": "red"},
                                  {"contact_email": "nope"}, {"faqs": "text"}])
def test_site_content_validation(world, body):
    assert admin(world).patch(C + "site/", body, format="json").status_code == 400


def test_site_content_cannot_change_name_slug_or_status(world):
    admin(world).patch(C + "site/", {"name": "Hacked", "slug": "hacked", "status": "suspended"}, format="json")
    world["a"].refresh_from_db()
    assert (world["a"].name, world["a"].slug, world["a"].status) == ("Alpha", "alpha", "active")


def test_services_crud_and_public_visibility(world):
    a = admin(world)
    s = a.post(C + "services/", {"name": "Wedding catering", "description": "Big events"}, format="json")
    assert s.status_code == 201 and s.data["slug"] == "wedding-catering"
    hidden = a.post(C + "services/", {"name": "Hidden", "is_active": False}, format="json")
    assert [x["name"] for x in json.loads(public().get(C + "public/services/").content)["data"]] == ["Wedding catering"]
    assert a.delete(f"{C}services/{s.data['id']}/").status_code == 405
    assert admin(world, "bravo").get(f"{C}services/{hidden.data['id']}/").status_code == 404


def test_gallery_upload_and_delete(world):
    a = admin(world)
    r = a.post(C + "gallery/", {"image": png(), "caption": "Dining room"}, format="multipart")
    assert r.status_code == 201
    assert len(json.loads(public().get(C + "public/gallery/").content)["data"]) == 1
    assert json.loads(public("bravo").get(C + "public/gallery/").content)["data"] == []
    assert a.post(C + "gallery/", {"image": SimpleUploadedFile("x.png", b"no", content_type="image/png")}, format="multipart").status_code == 400
    assert admin(world, "bravo").delete(f"{C}gallery/{r.data['id']}/").status_code == 404
    assert a.delete(f"{C}gallery/{r.data['id']}/").status_code == 204


def test_robots_and_sitemap_are_per_host(world):
    ca = mk_category(world)
    mk_product(world, ca, name="Fish stew")
    mk_product(world, ca, name="Hidden item", is_available=False)
    robots = public().get("/robots.txt").content.decode()
    assert "Sitemap: http://platform.test/alpha/sitemap.xml" in robots and "Disallow: /manage" in robots
    sm = public().get("/sitemap.xml").content.decode()
    assert "http://platform.test/alpha/menu/fish-stew" in sm and "hidden-item" not in sm and "bravo" not in sm
    assert "/pricing" in APIClient(HTTP_HOST=host()).get("/sitemap.xml").content.decode()
