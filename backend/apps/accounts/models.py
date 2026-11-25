from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from apps.core.tenancy import TimeStampedModel
from apps.core.uploads import random_upload_path


class Role(models.TextChoices):
    PLATFORM_ADMIN = "platform_admin", "Platform Administrator"  # represented by User.is_platform_admin
    RESTAURANT_ADMIN = "restaurant_admin", "Restaurant Administrator"
    MANAGER = "manager", "Branch Manager"
    CASHIER = "cashier", "Cashier"
    KITCHEN = "kitchen", "Kitchen Staff"
    WAITER = "waiter", "Waiter/Waitress"
    DELIVERY = "delivery", "Delivery Staff"
    CUSTOMER = "customer", "Customer"


ROLE_LEVEL = {
    Role.PLATFORM_ADMIN: 1,
    Role.RESTAURANT_ADMIN: 2,
    Role.MANAGER: 3,
    Role.CASHIER: 4,
    Role.KITCHEN: 5,
    Role.WAITER: 5,
    Role.DELIVERY: 5,
    Role.CUSTOMER: 6,
}
STAFF_ROLES = [r for r in Role.values if r not in (Role.PLATFORM_ADMIN, Role.CUSTOMER)]
BRANCH_SCOPED_ROLES = {Role.MANAGER, Role.CASHIER, Role.KITCHEN, Role.WAITER, Role.DELIVERY}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)  # hashes; None -> unusable password
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_admin", True)
        extra.setdefault("email_verified", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Global identity. Tenant roles live in Membership so one email can be a customer of many restaurants."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin site access only
    is_platform_admin = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    temp_password_expires_at = models.DateTimeField(null=True, blank=True)
    token_version = models.PositiveIntegerField(default=0)  # bump to revoke all issued JWTs
    mfa_enabled = models.BooleanField(default=False)  # a confirmed authenticator is enrolled (see accounts.mfa)
    avatar = models.ImageField(upload_to=random_upload_path("avatars"), blank=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list = []

    def __str__(self):
        return self.email


class Membership(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    restaurant = models.ForeignKey("tenants.Restaurant", on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=[(r, l) for r, l in Role.choices if r != Role.PLATFORM_ADMIN])
    branches = models.ManyToManyField("tenants.Branch", blank=True, related_name="memberships")
    is_active = models.BooleanField(default=True)
    preferences = models.JSONField(default=dict, blank=True)  # e.g. {"order_emails": true, "promotions": false}

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "restaurant"], name="uniq_membership_per_tenant")]
        indexes = [models.Index(fields=["restaurant", "role"])]

    def __str__(self):
        return f"{self.user.email} @ {self.restaurant.slug} ({self.role})"


class OneTimeCode(TimeStampedModel):
    """Short-lived 6-char code (email verification, password reset). Only an HMAC is stored."""

    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify_email"
        PASSWORD_RESET = "password_reset"
        EMAIL_CHANGE = "email_change"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="one_time_codes")
    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    salt = models.CharField(max_length=32)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    payload = models.CharField(max_length=254, blank=True)  # e.g. the pending new email address

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "-created_at"])]


class SetupToken(TimeStampedModel):
    """One-time password-setup link token (staff invitations, restaurant admin onboarding)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="setup_tokens")
    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)  # sha256 of a 256-bit random token
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class ConsentRecord(models.Model):
    class Method(models.TextChoices):
        CHECKBOX = "checkbox"
        GOOGLE_NOTICE = "google_oauth_notice"  # explicit notice shown on the Google sign-up screen

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents")
    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    terms_version = models.CharField(max_length=30)
    privacy_version = models.CharField(max_length=30)
    method = models.CharField(max_length=24, choices=Method.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    accepted_at = models.DateTimeField(auto_now_add=True)


class GoogleIdentity(TimeStampedModel):
    """Stable Google subject id. Linking is by `sub`, never by email alone."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="google_identities")
    sub = models.CharField(max_length=64, unique=True)


class MFADevice(TimeStampedModel):
    """TOTP authenticator of a user. The secret is stored encrypted; see accounts.mfa."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mfa_device")
    secret_enc = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_step = models.BigIntegerField(default=0)


class RecoveryCode(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_recovery_codes")
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
