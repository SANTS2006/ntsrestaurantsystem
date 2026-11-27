from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (BranchScopedQuerysetMixin, IsManagerOrAbove,
                                       IsRestaurantAdminOrAbove)
from apps.core.models import audit

from .geo import check_pin
from .models import Branch, Restaurant


class PublicRestaurantSerializer(serializers.ModelSerializer):
    """Only public branding/contact data. No settings, staff or financial fields."""

    class Meta:
        model = Restaurant
        fields = ["name", "slug", "logo", "primary_color", "secondary_color", "description",
                  "contact_email", "contact_phone", "address", "city", "country", "latitude", "longitude"]


class CurrentRestaurantView(APIView):
    """Public: the tenant website loads its own branding from the host-resolved restaurant."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        if request.tenant is None:
            return Response({"success": False, "error": {"code": "no_tenant", "message": "Not a restaurant host."}}, status=404)
        return Response({"success": True, "data": PublicRestaurantSerializer(request.tenant).data})


class BranchSerializer(serializers.ModelSerializer):
    manager_name = serializers.SerializerMethodField()
    staff_count = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = ["id", "name", "code", "address", "location", "latitude", "longitude", "phone", "email", "operating_hours", "status",
                  "manager", "manager_name", "staff_count"]
        # restaurant is never client-settable; status and manager change only through the audited actions below
        read_only_fields = ["id", "status", "manager"]

    def get_manager_name(self, b):
        return (b.manager.full_name or b.manager.email) if b.manager_id else None

    def get_staff_count(self, b):
        return b.memberships.filter(is_active=True).count()

    def validate_code(self, value):
        value = value.strip().upper()
        qs = Branch.unscoped.filter(restaurant=self.context["request"].tenant, code=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This branch code is already used.")
        return value

    def validate(self, data):
        return check_pin(data, self.instance)

    def validate_operating_hours(self, value):
        if not isinstance(value, dict) or len(value) > 7 or not all(isinstance(k, str) and isinstance(v, str) and len(v) <= 40 for k, v in value.items()):
            raise serializers.ValidationError('Use a mapping such as {"monday": "08:00-22:00"}.')
        return value


class BranchViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Branch.unscoped.select_related("manager").all()
    serializer_class = BranchSerializer
    branch_field = "id"
    http_method_names = ["get", "post", "patch", "head", "options"]  # branches are suspended, never deleted

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsManagerOrAbove()]
        return [IsRestaurantAdminOrAbove()]  # only restaurant admins create/edit/suspend branches

    def perform_create(self, serializer):
        branch = serializer.save(restaurant=self.request.tenant)
        audit("branch.created", actor=self.request.user, restaurant=self.request.tenant, obj=branch, request=self.request)

    def perform_update(self, serializer):
        branch = serializer.save()
        audit("branch.updated", actor=self.request.user, restaurant=self.request.tenant, obj=branch,
              metadata={"fields": sorted(serializer.validated_data)}, request=self.request)

    def _set_status(self, request, status_value):
        branch = self.get_object()
        if status_value == Branch.Status.SUSPENDED:
            from apps.cashier.models import Shift

            if Shift.unscoped.filter(branch=branch, status="open").exists():
                raise serializers.ValidationError({"detail": "Close the open cashier shifts at this branch before suspending it."})
        if branch.status != status_value:
            branch.status = status_value
            branch.save(update_fields=["status", "updated_at"])
            audit(f"branch.{'suspended' if status_value == Branch.Status.SUSPENDED else 'activated'}", actor=request.user,
                  restaurant=request.tenant, obj=branch, metadata={"reason": str(request.data.get("reason", ""))[:300]}, request=request)
        return Response(self.get_serializer(branch).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_status(request, Branch.Status.SUSPENDED)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._set_status(request, Branch.Status.ACTIVE)

    @action(detail=True, methods=["post"], url_path="assign-manager")
    def assign_manager(self, request, pk=None):
        """Set (or clear, with user_id=null) the branch's manager. The user must already be a manager of this restaurant."""
        from apps.accounts.models import Membership, Role

        branch = self.get_object()
        uid = request.data.get("user_id")
        with transaction.atomic():
            if branch.manager_id:  # the previous manager no longer works at this branch
                old = Membership.objects.filter(user_id=branch.manager_id, restaurant=request.tenant, role=Role.MANAGER).first()
                if old:
                    old.branches.remove(branch)
            if uid is None:
                branch.manager = None
            else:
                m = Membership.objects.filter(user_id=uid, restaurant=request.tenant, role=Role.MANAGER, is_active=True).select_related("user").first()
                if m is None:
                    raise serializers.ValidationError({"user_id": "Choose an active manager of this restaurant."})
                m.branches.add(branch)
                branch.manager = m.user
            branch.save(update_fields=["manager", "updated_at"])
            audit("branch.manager_assigned", actor=request.user, restaurant=request.tenant, obj=branch,
                  metadata={"manager_id": uid}, request=request)
        return Response(self.get_serializer(branch).data)
