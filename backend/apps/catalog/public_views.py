"""Customer-facing, unauthenticated endpoints. Tenant comes from the Host header only."""
from django.core.cache import cache
from django.db.models import Prefetch
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsRestaurantAdminOrAbove
from apps.core.models import audit
from apps.tenants.models import Branch
from apps.tenants.views import PublicRestaurantSerializer

from apps.payments.providers import online_payments_available
from .cache import MENU_TTL, menu_key
from .models import GalleryImage, Product, ProductAddon, ProductVariation, Service
from .policies import POLICY_TITLES, resolve_policies
from .serializers import _abs, public_product


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def tenant(self, request):
        if request.tenant is None:
            raise NotFound("Not a restaurant website.")
        return request.tenant


def _menu_queryset(tenant):
    return (Product.unscoped.filter(restaurant=tenant, is_archived=False, is_available=True, category__is_active=True)
            .select_related("category")
            .prefetch_related(Prefetch("variations", queryset=ProductVariation.unscoped.all()),
                              Prefetch("addons", queryset=ProductAddon.unscoped.all()))
            .order_by("category__sort_order", "category__name", "sort_order", "name"))


def _build_menu(request, tenant):
    categories, by_slug = [], {}
    for p in _menu_queryset(tenant):
        c = by_slug.get(p.category.slug)
        if c is None:
            c = by_slug[p.category.slug] = {"id": p.category_id, "slug": p.category.slug, "name": p.category.name,
                                            "description": p.category.description, "products": []}
            categories.append(c)
        c["products"].append(public_product(p, request))
    return categories


class PublicMenuView(PublicView):
    def get(self, request):
        tenant = self.tenant(request)
        key = menu_key(tenant.pk)
        menu = cache.get(key)
        if menu is None:
            menu = _build_menu(request, tenant)
            cache.set(key, menu, MENU_TTL)
        q = request.query_params.get("q", "").strip().lower()
        category = request.query_params.get("category", "")
        if category:
            menu = [c for c in menu if c["slug"] == category]
        if q:
            menu = [{**c, "products": [p for p in c["products"] if q in p["name"].lower() or q in p["description"].lower()]} for c in menu]
            menu = [c for c in menu if c["products"]]
        return Response(menu)


class PublicProductView(PublicView):
    def get(self, request, slug):
        tenant = self.tenant(request)
        p = _menu_queryset(tenant).filter(slug=slug).first()
        if p is None:
            raise NotFound("Product not found.")
        return Response(public_product(p, request))


class PublicServicesView(PublicView):
    def get(self, request):
        tenant = self.tenant(request)
        return Response([{"slug": s.slug, "name": s.name, "description": s.description, "image": _abs(request, s.image)}
                         for s in Service.unscoped.filter(restaurant=tenant, is_active=True)])


class PublicGalleryView(PublicView):
    def get(self, request):
        tenant = self.tenant(request)
        return Response([{"id": g.pk, "image": _abs(request, g.image), "caption": g.caption}
                         for g in GalleryImage.unscoped.filter(restaurant=tenant)])


class PublicSiteView(PublicView):
    """Everything the restaurant's public pages need besides the menu: branding, content, branches, policies."""

    def get(self, request):
        t = self.tenant(request)
        st = t.get_settings()
        branches = Branch.unscoped.filter(restaurant=t, status="active")
        return Response({
            "restaurant": PublicRestaurantSerializer(t, context={"request": request}).data,
            "url": t.public_url,
            "hero_title": st.hero_title or t.name, "hero_subtitle": st.hero_subtitle or t.description,
            "about_text": st.about_text or t.description, "delivery_info": st.delivery_info, "faqs": st.faqs,
            "currency": st.currency, "delivery_enabled": st.delivery_enabled, "pickup_enabled": st.pickup_enabled,
            "online_payments": st.online_payments_enabled and online_payments_available(),
            "seo_title": st.seo_title or t.name, "seo_description": st.seo_description or t.description[:160],
            "branches": [{"id": b.pk, "name": b.name, "address": b.address, "phone": b.phone, "email": b.email,
                          "operating_hours": b.operating_hours} for b in branches],
            "policies": [{"slug": k, "title": POLICY_TITLES[k]} for k in POLICY_TITLES],
        })


class PublicPolicyView(PublicView):
    def get(self, request, slug):
        t = self.tenant(request)
        policies = resolve_policies(t)
        if slug not in policies:
            raise NotFound("Policy not found.")
        return Response({"slug": slug, "title": POLICY_TITLES[slug], "text": policies[slug]})


# ---- restaurant-admin content editing --------------------------------------------------------------
class SiteContentSerializer(serializers.Serializer):
    hero_title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    hero_subtitle = serializers.CharField(max_length=250, required=False, allow_blank=True)
    about_text = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    delivery_info = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    seo_title = serializers.CharField(max_length=70, required=False, allow_blank=True)
    seo_description = serializers.CharField(max_length=160, required=False, allow_blank=True)
    faqs = serializers.ListField(child=serializers.DictField(child=serializers.CharField(max_length=1000)), required=False, max_length=30)
    policies = serializers.DictField(child=serializers.CharField(max_length=10000, allow_blank=True), required=False)
    # contact & branding the restaurant owns (name and slug remain platform-controlled)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    delivery_enabled = serializers.BooleanField(required=False)
    pickup_enabled = serializers.BooleanField(required=False)
    online_payments_enabled = serializers.BooleanField(required=False)
    qr_guest_orders_allowed = serializers.BooleanField(required=False)
    qr_identification = serializers.ChoiceField(choices=["none", "name", "phone"], required=False)
    delivery_fee = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    tax_rate_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    cashier_max_discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    email_footer = serializers.CharField(max_length=300, required=False, allow_blank=True)
    receipt_footer = serializers.CharField(max_length=200, required=False, allow_blank=True)
    reservations_enabled = serializers.BooleanField(required=False)
    reservation_auto_confirm = serializers.BooleanField(required=False)
    reservation_duration_minutes = serializers.IntegerField(min_value=30, max_value=300, required=False)
    reservation_max_party = serializers.IntegerField(min_value=1, max_value=100, required=False)
    primary_color = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    secondary_color = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise serializers.ValidationError("Choose a valid time zone such as Africa/Freetown.")
        return value

    def validate_faqs(self, value):
        if any(set(i) != {"q", "a"} or not i["q"].strip() or not i["a"].strip() for i in value):
            raise serializers.ValidationError('Each FAQ needs a non-empty "q" and "a".')
        return value

    def validate_policies(self, value):
        bad = set(value) - set(POLICY_TITLES)
        if bad:
            raise serializers.ValidationError(f"Unknown policy: {', '.join(sorted(bad))}.")
        return value


RESTAURANT_FIELDS = {"description", "contact_email", "contact_phone", "address", "city", "country", "primary_color", "secondary_color"}


class SiteContentView(APIView):
    permission_classes = [IsRestaurantAdminOrAbove]

    def get(self, request):
        t, st = request.tenant, request.tenant.get_settings()
        return Response({
            "hero_title": st.hero_title, "hero_subtitle": st.hero_subtitle, "about_text": st.about_text,
            "delivery_info": st.delivery_info, "seo_title": st.seo_title, "seo_description": st.seo_description,
            "faqs": st.faqs, "policies": st.policies, "policy_titles": POLICY_TITLES,
            "delivery_enabled": st.delivery_enabled, "pickup_enabled": st.pickup_enabled,
            "online_payments_enabled": st.online_payments_enabled,
            "qr_guest_orders_allowed": st.qr_guest_orders_allowed, "qr_identification": st.qr_identification,
            "delivery_fee": str(st.delivery_fee), "tax_rate_percent": str(st.tax_rate_percent),
            "cashier_max_discount_percent": str(st.cashier_max_discount_percent), "timezone": st.timezone,
            "email_footer": st.email_footer, "receipt_footer": st.receipt_footer, "reservations_enabled": st.reservations_enabled, "reservation_auto_confirm": st.reservation_auto_confirm,
            "reservation_duration_minutes": st.reservation_duration_minutes, "reservation_max_party": st.reservation_max_party,
            "description": t.description, "contact_email": t.contact_email, "contact_phone": t.contact_phone,
            "address": t.address, "city": t.city, "country": t.country,
            "primary_color": t.primary_color, "secondary_color": t.secondary_color,
        })

    def patch(self, request):
        s = SiteContentSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        t, st = request.tenant, request.tenant.get_settings()
        for k, v in s.validated_data.items():
            setattr(t if k in RESTAURANT_FIELDS else st, k, v)
        t.save()
        st.save()
        audit("site.content_updated", actor=request.user, restaurant=t, metadata={"fields": sorted(s.validated_data)}, request=request)
        return self.get(request)
