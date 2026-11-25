from rest_framework import serializers

from apps.core.models import AuditLog

from .models import PlatformSettings, Restaurant, SubscriptionPlan

LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}  # SVG deliberately excluded (script injection risk)


def validate_logo_file(value):
    if value is None:
        return value
    if value.size > LOGO_MAX_BYTES:
        raise serializers.ValidationError("Logo must be 2 MB or smaller.")
    image = getattr(value, "image", None)  # populated by DRF's ImageField via Pillow (real decode, not extension)
    if image is None or image.format not in LOGO_FORMATS:
        raise serializers.ValidationError("Logo must be a PNG, JPEG or WebP image.")
    return value


class RestaurantAdminSerializer(serializers.ModelSerializer):
    public_url = serializers.CharField(read_only=True)
    branches_count = serializers.IntegerField(read_only=True, default=0)
    staff_count = serializers.IntegerField(read_only=True, default=0)
    customers_count = serializers.IntegerField(read_only=True, default=0)
    plan_name = serializers.CharField(source="plan.name", read_only=True, default=None)

    class Meta:
        model = Restaurant
        fields = ["id", "name", "slug", "status", "logo", "primary_color", "secondary_color", "description",
                  "contact_email", "contact_phone", "address", "city", "country", "plan", "plan_name", "public_url",
                  "branches_count", "staff_count", "customers_count", "created_at"]
        read_only_fields = ["id", "status", "created_at"]  # status only changes through suspend/activate actions

    def validate_logo(self, value):
        return validate_logo_file(value)


class RestaurantRegistrationSerializer(RestaurantAdminSerializer):
    admin_full_name = serializers.CharField(max_length=150, write_only=True)
    admin_email = serializers.EmailField(write_only=True)

    class Meta(RestaurantAdminSerializer.Meta):
        fields = RestaurantAdminSerializer.Meta.fields + ["admin_full_name", "admin_email"]

    def create(self, validated_data):
        validated_data.pop("admin_full_name"), validated_data.pop("admin_email")
        return super().create(validated_data)


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = ["platform_name", "whatsapp_number", "support_email"]

    def validate_whatsapp_number(self, value):
        value = value.strip().lstrip("+")
        if value and not (value.isdigit() and 8 <= len(value) <= 15):
            raise serializers.ValidationError("Use international format with digits only, e.g. 23276123456.")
        return value


class PublicPlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = ["platform_name", "whatsapp_number", "support_email"]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ["id", "name", "slug", "description", "price", "currency", "interval", "features",
                  "max_branches", "is_active", "is_featured", "sort_order"]

    def validate_features(self, value):
        if not isinstance(value, list) or not all(isinstance(f, str) and len(f) <= 120 for f in value):
            raise serializers.ValidationError("Features must be a list of short strings.")
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, default=None)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "created_at", "action", "actor_email", "restaurant", "restaurant_name",
                  "object_type", "object_id", "metadata", "ip_address"]
