import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.core.tenancy import TimeStampedModel

hex_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a hex colour like #1a2b3c.")
# A restaurant lives at https://<platform domain>/<slug>, so its slug must never equal a top-level platform path.
RESERVED_SLUGS = {
    "www", "api", "admin", "app", "static", "mail", "platform", "root", "support", "ws", "media", "assets", "django-admin",
    "healthz", "readyz", "robots", "sitemap", "login", "register", "logout", "features", "pricing", "about", "faq", "contact",
    "legal", "terms", "privacy", "forgot-password", "setup-password", "verify-email", "favicon", "logo", "index", "new", "null", "undefined",
}


def validate_slug(value):
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?", value) or value in RESERVED_SLUGS:
        raise ValidationError("Slug must be lowercase letters, digits or hyphens and not reserved.")


def logo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return f"restaurants/logos/{uuid.uuid4().hex}.{ext}"  # randomised: no user-controlled names on disk


class SubscriptionPlan(TimeStampedModel):
    """Platform-configurable pricing plan (shown on the marketing site, assignable to restaurants)."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="USD")
    interval = models.CharField(max_length=10, choices=[("month", "Monthly"), ("year", "Yearly")], default="month")
    features = models.JSONField(default=list, blank=True)
    max_branches = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return self.name


class Restaurant(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=50, unique=True, validators=[validate_slug])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    logo = models.ImageField(upload_to=logo_path, blank=True)
    plan = models.ForeignKey(SubscriptionPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="restaurants")
    primary_color = models.CharField(max_length=7, default="#0a72e0", validators=[hex_color])
    secondary_color = models.CharField(max_length=7, default="#0b3f93", validators=[hex_color])
    description = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)

    # Plain manager is intentionally unscoped: Restaurant *is* the tenant.
    unscoped_objects = models.Manager()
    objects = models.Manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_settings(self):
        """Settings row, created on first use (older/imported restaurants may not have one)."""
        return RestaurantSettings.objects.get_or_create(restaurant=self)[0]

    @property
    def public_url(self):
        return f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}/{self.slug}"


class RestaurantDomain(TimeStampedModel):
    """Custom domains (future): verified hostnames that resolve to a restaurant."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField(max_length=253, unique=True)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.hostname = self.hostname.lower().strip().rstrip(".")
        super().save(*args, **kwargs)


class RestaurantSettings(TimeStampedModel):
    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name="settings")
    currency = models.CharField(max_length=3, default="SLE")
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    delivery_enabled = models.BooleanField(default=True)
    pickup_enabled = models.BooleanField(default=True)
    allow_partial_payments = models.BooleanField(default=False)
    online_payments_enabled = models.BooleanField(default=False)
    qr_guest_orders_allowed = models.BooleanField(default=True)
    qr_identification = models.CharField(max_length=6, default="none", choices=[("none", "Nothing"), ("name", "Name"), ("phone", "Name and phone")])
    inventory_tracking_enabled = models.BooleanField(default=False)
    cashier_max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))  # larger discounts need a manager
    email_footer = models.CharField(max_length=300, blank=True)  # extra line at the bottom of every email this restaurant sends
    reservations_enabled = models.BooleanField(default=True)
    reservation_auto_confirm = models.BooleanField(default=True)
    reservation_duration_minutes = models.PositiveSmallIntegerField(default=90)
    reservation_max_party = models.PositiveSmallIntegerField(default=12)
    timezone = models.CharField(max_length=64, default="UTC")  # IANA name; reports follow it
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=160, blank=True)
    # Public website content (edited by the restaurant administrator)
    hero_title = models.CharField(max_length=120, blank=True)
    hero_subtitle = models.CharField(max_length=250, blank=True)
    about_text = models.TextField(blank=True)
    delivery_info = models.TextField(blank=True)
    faqs = models.JSONField(default=list, blank=True)  # [{"q": "...", "a": "..."}]
    policies = models.JSONField(default=dict, blank=True)  # {policy-slug: text}; empty -> generic default


class Branch(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="branches")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20)
    address = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    operating_hours = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_branches")

    unscoped = models.Manager()
    objects = models.Manager()

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "code"], name="uniq_branch_code_per_restaurant")]

    def __str__(self):
        return f"{self.restaurant.name} / {self.name}"


class PlatformSettings(models.Model):
    """Singleton: platform-owner configuration (WhatsApp contact, support details...)."""

    whatsapp_number = models.CharField(max_length=20, blank=True, help_text="International format, digits only.")
    support_email = models.EmailField(blank=True)
    platform_name = models.CharField(max_length=100, default="NTS Restaurant Platform")
    # Platform-wide switch: when on, platform and restaurant administrators must use two-step verification.
    # Changed only through POST /platform/settings/mfa/ (password + code re-check, audited).
    mfa_enforced = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]
