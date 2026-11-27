"""What visitors send through the website contact forms, and what the platform owner writes on the main website."""
from django.conf import settings
from django.db import models

from apps.core.uploads import random_upload_path


class ContactMessage(models.Model):
    """One submission of a contact form. `restaurant` is empty for messages sent through the platform's own website.
    Messages are never deleted: unwanted ones are marked as spam."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        REPLIED = "replied", "Replied"
        CLOSED = "closed", "Closed"
        SPAM = "spam", "Spam"

    class Topic(models.TextChoices):
        GENERAL = "general", "General question"
        ORDER = "order", "An order or payment"
        RESERVATION = "reservation", "A reservation or event"
        FEEDBACK = "feedback", "Feedback or complaint"
        SALES = "sales", "Bringing my restaurant online"
        SUPPORT = "support", "Help with the system"
        OTHER = "other", "Something else"

    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("tenants.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    business_name = models.CharField(max_length=150, blank=True)  # the enquirer's restaurant (platform form)
    city = models.CharField(max_length=100, blank=True)
    preferred_contact = models.CharField(max_length=10, choices=[("email", "Email"), ("phone", "Phone call"), ("whatsapp", "WhatsApp")], default="email")
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.GENERAL)
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=4000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    page = models.CharField(max_length=200, blank=True)
    consented_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["restaurant", "status", "-created_at"])]

    @property
    def reference(self):
        return f"MSG-{self.pk:06d}"


class ContactActivity(models.Model):
    """What the team did about a message: replies, internal notes and status changes. Append-only."""

    message = models.ForeignKey(ContactMessage, on_delete=models.CASCADE, related_name="activity")
    kind = models.CharField(max_length=8, choices=[("reply", "Reply sent"), ("note", "Internal note"), ("status", "Status change")])
    text = models.TextField(max_length=4000)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Message history is append-only.")
        super().save(*args, **kwargs)


class PlatformContent(models.Model):
    """Singleton: the texts of the platform's public website. Only what differs from the defaults is stored."""

    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


HERO_SLOTS = ["home", "features", "pricing", "about", "faq", "contact", "legal"]


class PlatformImage(models.Model):
    """The picture behind the heading of one page of the platform website."""

    slot = models.CharField(max_length=20, unique=True, choices=[(s, s) for s in HERO_SLOTS])
    image = models.ImageField(upload_to=random_upload_path("platform/heroes"))
    updated_at = models.DateTimeField(auto_now=True)
