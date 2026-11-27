"""The page builder: for each public page of the platform website or of a restaurant website, the heading (hero) and any number of
content sections, each shown as cards, an accordion, a carousel, a picture with text, a gallery, a banner or plain text.

Only data is stored: no HTML, no scripts. Pictures are referred to by the id of an upload that belongs to the same website, and
links must stay inside the site or be https, telephone or email links.
"""
import re

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsPlatformAdminOnPlatformHost, IsRestaurantAdminOrAbove
from apps.core.models import audit
from apps.core.uploads import image_field

from .models import PageDesign, SiteAsset

PLATFORM_PAGES = [("home", "Home"), ("features", "Features"), ("pricing", "Pricing"), ("about", "About"), ("faq", "FAQ"), ("contact", "Contact"), ("legal", "Legal pages")]
RESTAURANT_PAGES = [("home", "Home"), ("menu", "Menu"), ("services", "Services"), ("gallery", "Gallery"), ("catering", "Catering"),
                    ("reserve", "Reserve"), ("about", "About"), ("contact", "Contact"), ("faq", "FAQ")]
LAYOUTS = ["cards", "accordion", "carousel", "split", "gallery", "banner", "text"]
MODELS = ["auto", "none", "cloche", "burger", "drink", "cake", "globe"]
CHOICES = {"layout": LAYOUTS, "placement": ["top", "bottom"], "background": ["plain", "soft", "brand", "dark"],
           "animation": ["rise", "zoom", "left", "right", "flip", "none"]}
MAX_BLOCKS, MAX_ITEMS, MAX_ASSETS = 20, 24, 300
ASSET_MAX_BYTES = 4 * 1024 * 1024
_LINK = re.compile(r"^(/(?![/\\])[^\s\\]*|https://[^\s]+|tel:\+?[\d\s()-]+|mailto:[^\s@]+@[^\s@]+)$")


def pages_for(request):
    return PLATFORM_PAGES if request.tenant is None else RESTAURANT_PAGES


def _bad(message):
    raise ValidationError({"detail": message})


def _text(data, key, limit, where):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        _bad(f"{where}: {key.replace('_', ' ')} must be text of at most {limit} characters.")
    return value.replace("\r\n", "\n").strip()


def _choice(data, key, allowed, where):
    value = data.get(key, allowed[0])
    if value not in allowed:
        _bad(f"{where}: unknown {key}.")
    return value


def _link(data, where):
    value = _text(data, "button_link", 300, where)
    if value and not _LINK.match(value):
        _bad(f"{where}: a button link starts with / (a page of this website), https://, tel: or mailto:.")
    return value


def _image(data, owned, where):
    value = data.get("image")
    if value is None or value == "":
        return None
    if not isinstance(value, int) or value not in owned:
        _bad(f"{where}: choose a picture you uploaded to this website.")
    return value


def clean_design(body, owned):
    """Validate what the editor sent. `owned` is the set of picture ids that belong to this website."""
    if not isinstance(body, dict) or set(body) - {"hero", "blocks"}:
        _bad("Send the heading and the sections of the page.")
    h = body.get("hero") or {}
    if not isinstance(h, dict):
        _bad("The heading is not valid.")
    hero = {"eyebrow": _text(h, "eyebrow", 80, "Heading"), "title": _text(h, "title", 120, "Heading"), "lead": _text(h, "lead", 400, "Heading"),
            "button_label": _text(h, "button_label", 40, "Heading"), "button_link": _link(h, "Heading"),
            "model": _choice(h, "model", MODELS, "Heading"), "image": _image(h, owned, "Heading")}
    raw = body.get("blocks") or []
    if not isinstance(raw, list) or len(raw) > MAX_BLOCKS:
        _bad(f"A page holds at most {MAX_BLOCKS} sections.")
    blocks = []
    for n, b in enumerate(raw, 1):
        where = f"Section {n}"
        if not isinstance(b, dict):
            _bad(f"{where} is not valid.")
        items = b.get("items") or []
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            _bad(f"{where}: at most {MAX_ITEMS} entries.")
        clean_items = []
        for i, item in enumerate(items, 1):
            spot = f"{where}, entry {i}"
            if not isinstance(item, dict):
                _bad(f"{spot} is not valid.")
            clean_items.append({"title": _text(item, "title", 150, spot), "text": _text(item, "text", 3000, spot), "image": _image(item, owned, spot),
                                "button_label": _text(item, "button_label", 40, spot), "button_link": _link(item, spot)})
        columns = b.get("columns", 3)
        if columns not in (2, 3, 4):
            _bad(f"{where}: choose 2, 3 or 4 columns.")
        block = {key: _choice(b, key, allowed, where) for key, allowed in CHOICES.items()}
        block.update({"columns": columns, "visible": b.get("visible", True) is True, "autoplay": b.get("autoplay", False) is True,
                      "model": _choice(b, "model", MODELS[1:], where), "eyebrow": _text(b, "eyebrow", 80, where), "title": _text(b, "title", 150, where),
                      "text": _text(b, "text", 4000, where), "image": _image(b, owned, where), "button_label": _text(b, "button_label", 40, where),
                      "button_link": _link(b, where), "items": clean_items})
        blocks.append(block)
    return {"hero": hero, "blocks": blocks}


def _urls(request):
    out = {}
    for asset in SiteAsset.objects.filter(restaurant=request.tenant):
        try:
            out[asset.pk] = request.build_absolute_uri(asset.image.url)
        except Exception:  # noqa: BLE001 - a storage hiccup must not break the website
            pass
    return out


def _with_urls(design, urls):
    def fill(row):
        return {**row, "image_url": urls.get(row.get("image"))}

    return {"hero": fill(design.get("hero", {})), "blocks": [{**fill(b), "items": [fill(i) for i in b.get("items", [])]} for b in design.get("blocks", [])]}


class PublicPagesView(APIView):
    """What visitors see: each designed page's heading and its visible sections."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        if request.tenant is None and not getattr(request, "is_platform", False):
            raise NotFound()
        rows = list(PageDesign.objects.filter(restaurant=request.tenant))
        urls = _urls(request) if rows else {}
        pages = {}
        for row in rows:
            shown = {**row.data, "blocks": [b for b in row.data.get("blocks", []) if b.get("visible")]}
            pages[row.page] = _with_urls(shown, urls)
        return Response({"pages": pages})


class CanDesign(BasePermission):
    """The platform website: platform administrators. A restaurant website: its administrators."""

    def has_permission(self, request, view):
        if request.tenant is None:
            return IsPlatformAdminOnPlatformHost().has_permission(request, view)
        return IsRestaurantAdminOrAbove().has_permission(request, view)


class BuilderView(APIView):
    permission_classes = [CanDesign]

    def get(self, request):
        urls = _urls(request)
        stored = {r.page: _with_urls(r.data, urls) for r in PageDesign.objects.filter(restaurant=request.tenant)}
        return Response({"pages": [{"id": key, "label": label} for key, label in pages_for(request)], "designs": stored})


class BuilderPageView(APIView):
    permission_classes = [CanDesign]

    def put(self, request, page):
        if page not in dict(pages_for(request)):
            raise NotFound()
        owned = set(SiteAsset.objects.filter(restaurant=request.tenant).values_list("pk", flat=True))
        design = clean_design(request.data, owned)
        with transaction.atomic():
            row = PageDesign.objects.select_for_update().filter(restaurant=request.tenant, page=page).first() or PageDesign(restaurant=request.tenant, page=page)
            row.data, row.updated_by = design, request.user
            row.save()
            audit("website.page_designed", actor=request.user, restaurant=request.tenant, obj=row,
                  metadata={"page": page, "sections": len(design["blocks"])}, request=request)
        return Response(_with_urls(design, _urls(request)))


class AssetInput(serializers.Serializer):
    image = image_field(ASSET_MAX_BYTES)


class BuilderImageView(APIView):
    permission_classes = [CanDesign]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        if SiteAsset.objects.filter(restaurant=request.tenant).count() >= MAX_ASSETS:
            _bad(f"This website already has {MAX_ASSETS} pictures.")
        s = AssetInput(data=request.data)
        s.is_valid(raise_exception=True)
        asset = SiteAsset.objects.create(restaurant=request.tenant, image=s.validated_data["image"], uploaded_by=request.user)
        audit("website.picture_uploaded", actor=request.user, restaurant=request.tenant, obj=asset, request=request)
        return Response({"id": asset.pk, "url": request.build_absolute_uri(asset.image.url)}, status=201)
