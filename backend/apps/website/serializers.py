from rest_framework import serializers

from apps.tenants.models import Branch

from .models import ContactMessage


class ContactInput(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=150)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    business_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    preferred_contact = serializers.ChoiceField(choices=["email", "phone", "whatsapp"], default="email")
    topic = serializers.ChoiceField(choices=ContactMessage.Topic.values, default="general")
    subject = serializers.CharField(min_length=3, max_length=150)
    message = serializers.CharField(min_length=10, max_length=4000)
    branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    page = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    consent = serializers.BooleanField()

    def validate_phone(self, value):
        if value and (any(c not in "+0123456789 ()-." for c in value) or sum(c.isdigit() for c in value) < 6):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate_consent(self, value):
        if value is not True:
            raise serializers.ValidationError("Please agree so that we can answer you.")
        return value

    def validate(self, data):
        if data["preferred_contact"] != "email" and not data["phone"]:
            raise serializers.ValidationError({"phone": "Add your phone number so we can reach you that way."})
        tenant = self.context["request"].tenant
        data["branch"] = None
        if data.get("branch_id") is not None:
            branch = Branch.unscoped.filter(pk=data["branch_id"], restaurant=tenant, status="active").first() if tenant else None
            if branch is None:
                raise serializers.ValidationError({"branch_id": "Choose one of the listed locations."})
            data["branch"] = branch
        return data


def message_row(m):
    return {"id": m.pk, "reference": m.reference, "name": m.name, "email": m.email, "phone": m.phone, "business_name": m.business_name,
            "topic": m.topic, "topic_label": m.get_topic_display(), "subject": m.subject, "preview": m.message[:140],
            "status": m.status, "status_label": m.get_status_display(), "branch": m.branch.name if m.branch_id else None,
            "created_at": m.created_at}


def _who(user):
    return (user.full_name or user.email) if user else None


def message_detail(m):
    return {**message_row(m), "message": m.message, "city": m.city, "preferred_contact": m.preferred_contact,
            "preferred_contact_label": m.get_preferred_contact_display(), "page": m.page, "consented_at": m.consented_at,
            "has_account": m.user_id is not None, "ip_address": m.ip_address, "user_agent": m.user_agent,
            "handled_by": _who(m.handled_by), "updated_at": m.updated_at,
            "activity": [{"id": a.pk, "kind": a.kind, "text": a.text, "author": _who(a.author), "created_at": a.created_at}
                         for a in m.activity.select_related("author")]}
