from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.models import Membership, Role
from rest_framework.exceptions import ValidationError

from apps.accounts.permissions import IsPlatformAdminOnPlatformHost
from apps.core.models import AuditLog, audit

from .models import Branch, PlatformSettings, Restaurant, RestaurantSettings, SubscriptionPlan
from .platform_serializers import (AuditLogSerializer, PlatformSettingsSerializer,
                                   PublicPlatformSettingsSerializer, RestaurantAdminSerializer,
                                   RestaurantRegistrationSerializer, SubscriptionPlanSerializer)


class PublicSettingsView(APIView):
    """Marketing-site data: platform name, WhatsApp number, support email."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"success": True, "data": PublicPlatformSettingsSerializer(PlatformSettings.load()).data})


class PublicPlansView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True)
        return Response({"success": True, "data": SubscriptionPlanSerializer(plans, many=True).data})


class PlatformSettingsView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        return Response({"success": True, "data": PlatformSettingsSerializer(PlatformSettings.load()).data})

    def patch(self, request):
        obj = PlatformSettings.load()
        s = PlatformSettingsSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit("platform.settings_updated", actor=request.user, metadata={"fields": sorted(s.validated_data)}, request=request)
        return Response({"success": True, "data": s.data})


class MfaPolicyView(APIView):
    """Turn the platform-wide two-step-verification requirement on or off. Needs the administrator's password and, if they have
    two-step verification, a current code. Turning it off also lets administrators switch their own factor off. Audited."""

    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        from apps.accounts import mfa

        return Response({"success": True, "data": {"enforced": mfa.enforced(), "master_switch": bool(settings.MFA_ENFORCEMENT)}})

    def post(self, request):
        from django.contrib.auth import authenticate

        from apps.accounts import mfa

        want = request.data.get("enforced")
        if not isinstance(want, bool):
            raise ValidationError({"enforced": "Send true or false."})
        if not settings.MFA_ENFORCEMENT:
            raise ValidationError({"enforced": "Two-step verification is disabled in the server configuration (MFA_ENFORCEMENT)."})
        u = request.user
        if authenticate(request, username=u.email, password=str(request.data.get("password", ""))) is None:
            audit("platform.mfa_policy_refused", actor=u, metadata={"reason": "password"}, request=request)
            raise ValidationError({"password": "Your password is not correct."})
        if mfa.challenge_required(u):
            ok, how = mfa.verify(u, str(request.data.get("code", "")))
            if not ok:
                audit("platform.mfa_policy_refused", actor=u, metadata={"reason": f"mfa:{how}"}, request=request)
                raise ValidationError({"code": "Enter a current code from your authenticator app."})
        obj = PlatformSettings.load()
        obj.mfa_enforced = want
        obj.save(update_fields=["mfa_enforced"])
        audit("platform.mfa_enforced" if want else "platform.mfa_not_enforced", actor=u, request=request)
        return Response({"success": True, "data": {"enforced": mfa.enforced(), "master_switch": True}})


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPlatformAdminOnPlatformHost]
    queryset = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]  # plans are deactivated, not deleted

    def perform_create(self, serializer):
        plan = serializer.save()
        audit("plan.created", actor=self.request.user, obj=plan, request=self.request)

    def perform_update(self, serializer):
        plan = serializer.save()
        audit("plan.updated", actor=self.request.user, obj=plan, metadata={"fields": sorted(serializer.validated_data)}, request=self.request)


class PlatformRestaurantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                                mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Restaurants are never deleted (financial history): suspend instead."""

    permission_classes = [IsPlatformAdminOnPlatformHost]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Restaurant.unscoped_objects.select_related("plan").annotate(
            branches_count=Count("branches", distinct=True),
            staff_count=Count("memberships", filter=~Q(memberships__role=Role.CUSTOMER), distinct=True),
            customers_count=Count("memberships", filter=Q(memberships__role=Role.CUSTOMER), distinct=True),
        )
        p = self.request.query_params
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(contact_email__icontains=q))
        if p.get("status") in ("active", "suspended"):
            qs = qs.filter(status=p["status"])
        return qs.order_by("name")

    def get_serializer_class(self):
        return RestaurantRegistrationSerializer if self.action == "create" else RestaurantAdminSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        with transaction.atomic():  # tenant, settings, default branch, admin and onboarding email succeed or fail together
            restaurant = s.save()
            RestaurantSettings.objects.create(restaurant=restaurant, seo_title=restaurant.name[:70],
                                              seo_description=restaurant.description[:160])
            Branch.unscoped.create(restaurant=restaurant, name="Main Branch", code="MAIN", address=restaurant.address,
                                   phone=restaurant.contact_phone, email=restaurant.contact_email)
            try:
                services.onboard_restaurant_admin(request, restaurant, d["admin_email"], d["admin_full_name"])
            except services.FlowError as e:
                transaction.set_rollback(True)
                return Response({"success": False, "error": {"code": e.code, "message": e.message}}, status=e.status)
            audit("restaurant.registered", actor=request.user, restaurant=restaurant, obj=restaurant,
                  metadata={"slug": restaurant.slug}, request=request)
        restaurant = self.get_queryset().get(pk=restaurant.pk)
        return Response({"success": True, "data": RestaurantAdminSerializer(restaurant, context={"request": request}).data}, status=201)

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        audit("restaurant.updated", actor=request.user, restaurant=self.get_object(), obj=self.get_object(),
              metadata={"fields": sorted(request.data.keys())}, request=request)
        return response

    def _set_status(self, request, status_value, action_name):
        restaurant = self.get_object()
        if restaurant.status != status_value:
            Restaurant.unscoped_objects.filter(pk=restaurant.pk).update(status=status_value)
            audit(f"restaurant.{action_name}", actor=request.user, restaurant=restaurant, obj=restaurant,
                  metadata={"reason": str(request.data.get("reason", ""))[:300]}, request=request)
        restaurant = self.get_queryset().get(pk=restaurant.pk)
        return Response({"success": True, "data": RestaurantAdminSerializer(restaurant, context={"request": request}).data})

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_status(request, Restaurant.Status.SUSPENDED, "suspended")

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._set_status(request, Restaurant.Status.ACTIVE, "activated")


class PlatformDashboardView(APIView):
    """Global counts. Order/payment/revenue figures arrive with Phases 5-6 (no placeholder numbers)."""

    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        r = Restaurant.unscoped_objects
        m = Membership.objects.filter(is_active=True)
        return Response({"success": True, "data": {
            "restaurants_total": r.count(),
            "restaurants_active": r.filter(status="active").count(),
            "restaurants_suspended": r.filter(status="suspended").count(),
            "branches_total": Branch.unscoped.count(),
            "customers_total": m.filter(role=Role.CUSTOMER).count(),
            "employees_total": m.exclude(role=Role.CUSTOMER).count(),
        }})


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsPlatformAdminOnPlatformHost]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor", "restaurant").order_by("-created_at")
        p = self.request.query_params
        if p.get("action"):
            qs = qs.filter(action__startswith=p["action"])
        if p.get("restaurant", "").isdigit():
            qs = qs.filter(restaurant_id=int(p["restaurant"]))
        if p.get("actor"):
            qs = qs.filter(actor__email__icontains=p["actor"][:120])
        for key, lookup in (("from", "created_at__date__gte"), ("to", "created_at__date__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lookup: __import__("datetime").date.fromisoformat(p[key])})
                except ValueError:
                    raise ValidationError({key: "Use the format YYYY-MM-DD."})
        return qs
