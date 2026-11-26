"""Staff management: list, edit, (de)activate, re-invite, review activity.

Rules enforced on the server for every call:
* only people strictly *below* the actor in the role hierarchy can be edited (no peers, no superiors, never yourself);
* a manager only sees staff who work at branches the manager has, and may only edit staff whose branches are ALL within the
  manager's own; a manager can never give anyone access to a branch they do not manage;
* customers are never listed here; names/phones of people who also work elsewhere are not editable from this restaurant.
"""
from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.cashier.models import Shift
from apps.core.models import AuditLog, audit
from apps.tenants.models import Branch

from . import services
from .models import ROLE_LEVEL, Membership, Role, User
from .permissions import IsManagerOrAbove, accessible_branch_ids, can_assign_role, effective_role


def member_json(m):
    u = m.user
    return {"id": m.pk, "user_id": u.pk, "full_name": u.full_name, "email": u.email, "phone": u.phone, "role": m.role,
            "role_label": Role(m.role).label, "is_active": m.is_active, "invite_pending": not u.email_verified,
            "branches": [{"id": b.pk, "name": b.name} for b in m.branches.all()], "joined": m.created_at}


class StaffUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=[r for r in Role.values if r not in (Role.PLATFORM_ADMIN, Role.CUSTOMER)], required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class StaffViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsManagerOrAbove]

    # ---- scoping ---------------------------------------------------------------------------------
    def get_queryset(self):
        qs = (Membership.objects.filter(restaurant=self.request.tenant).exclude(role=Role.CUSTOMER)
              .select_related("user").prefetch_related("branches"))
        role = effective_role(self.request)
        if role not in (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN):
            qs = qs.filter(branches__in=accessible_branch_ids(self.request)).distinct()
        p = self.request.query_params
        if p.get("role") in Role.values:
            qs = qs.filter(role=p["role"])
        if p.get("branch", "").isdigit():
            qs = qs.filter(branches__id=int(p["branch"]))
        if p.get("active") in ("0", "1"):
            qs = qs.filter(is_active=p["active"] == "1")
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(user__full_name__icontains=q) | Q(user__email__icontains=q))
        return qs.order_by("user__full_name", "id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([member_json(m) for m in page])

    def retrieve(self, request, *args, **kwargs):
        return Response(member_json(self.get_object()))

    # ---- authorisation helpers -----------------------------------------------------------------
    def _editable(self, request, m):
        """Return an error string if the actor may not modify this membership, else None."""
        actor_role = effective_role(request)
        if m.user_id == request.user.pk:
            return "You cannot change your own role, branches or status."
        if not can_assign_role(actor_role, m.role):
            return "You cannot manage someone at or above your own level."
        if actor_role not in (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN):
            mine = accessible_branch_ids(request)
            if not {b.pk for b in m.branches.all()} <= mine:
                return "This person also works at branches you do not manage."
        return None

    def _locked(self, request, pk):
        m = (Membership.objects.select_for_update().filter(pk=pk, restaurant=request.tenant).exclude(role=Role.CUSTOMER)
             .select_related("user").first())
        if m is None or not self.get_queryset().filter(pk=pk).exists():
            raise NotFound()
        problem = self._editable(request, m)
        if problem:
            raise serializers.ValidationError({"detail": problem})
        return m

    # ---- correct a mistyped e-mail address --------------------------------------------------------
    def _change_email(self, request, m, new, changes):
        """Fix a wrong address. Only for people who work for this restaurant alone. Their sessions end, they must prove they own the
        new mailbox (an invitation link if they never set a password, otherwise a verification code)."""
        from apps.accounts import codes
        from apps.notifications.services import queue_email

        user = m.user
        if user.is_platform_admin:
            raise serializers.ValidationError({"email": "Platform administrators change their own address."})
        if Membership.objects.filter(user=user).exclude(restaurant=request.tenant).exists():
            raise serializers.ValidationError({"email": "This person also works elsewhere; only they can change their email."})
        if User.objects.filter(email__iexact=new).exclude(pk=user.pk).exists():
            raise serializers.ValidationError({"email": "Another account already uses this email."})
        old, pending = user.email, not user.email_verified
        user.email = new
        user.email_verified = False
        user.token_version += 1  # signs them out everywhere
        user.save(update_fields=["email", "email_verified", "token_version"])
        if pending:  # never accepted the invitation: send it again, to the right address
            raw = services.issue_setup_token(user, request.tenant)
            queue_email("staff_invitation", new, {"name": user.full_name, "email": new, "role_label": Role(m.role).label,
                        "setup_url": services.setup_url(request.tenant, raw), "login_url": services.login_url(request.tenant)}, restaurant=request.tenant)
        else:
            code = codes.issue_code(user, "verify_email", request.tenant)
            if code:
                queue_email("verify_email", new, {"name": user.full_name, "code": code}, restaurant=request.tenant)
            queue_email("email_changed", old, {"name": user.full_name, "new_email": new}, restaurant=request.tenant)
        changes["email"] = [old, new]

    # ---- edit ----------------------------------------------------------------------------------
    @transaction.atomic
    def partial_update(self, request, pk=None):
        m = self._locked(request, pk)
        s = StaffUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        actor_role = effective_role(request)
        changes = {}
        new_role = d.get("role", m.role)
        if new_role != m.role:
            if not can_assign_role(actor_role, new_role):
                raise serializers.ValidationError({"role": "You cannot assign this role."})
            changes["role"] = [m.role, new_role]
        if "branch_ids" in d or new_role != m.role:
            ids = d.get("branch_ids", [b.pk for b in m.branches.all()])
            branches = list(Branch.unscoped.filter(restaurant=request.tenant, pk__in=ids))
            if len(branches) != len(set(ids)):
                raise serializers.ValidationError({"branch_ids": "Unknown branch."})
            if new_role == Role.RESTAURANT_ADMIN:
                branches = []
            elif not branches:
                raise serializers.ValidationError({"branch_ids": "Select at least one branch for this role."})
            if actor_role not in (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN) and not {b.pk for b in branches} <= accessible_branch_ids(request):
                raise serializers.ValidationError({"branch_ids": "You can only assign branches you manage."})
            before = sorted(b.pk for b in m.branches.all())
            if before != sorted(b.pk for b in branches):
                changes["branches"] = [before, sorted(b.pk for b in branches)]
            m.role = new_role
            m.save(update_fields=["role", "updated_at"])
            m.branches.set(branches)
            if new_role != Role.MANAGER:  # a branch manager that is no longer a manager stops being "the" manager
                Branch.unscoped.filter(restaurant=request.tenant, manager=m.user).update(manager=None)
        if "email" in d and d["email"].lower() != m.user.email:
            self._change_email(request, m, d["email"].lower(), changes)
        user_fields = {k: d[k] for k in ("full_name", "phone") if k in d}
        if user_fields:
            if Membership.objects.filter(user=m.user).exclude(restaurant=request.tenant).exists():
                raise serializers.ValidationError({"detail": "This person also works elsewhere; their name and phone can only be changed by themselves."})
            for k, v in user_fields.items():
                setattr(m.user, k, v)
            m.user.save(update_fields=list(user_fields))
            changes["profile"] = sorted(user_fields)
        if changes:
            audit("staff.updated", actor=request.user, restaurant=request.tenant, obj=m, metadata={"changes": changes}, request=request)
        m = Membership.objects.select_related("user").prefetch_related("branches").get(pk=m.pk)
        return Response(member_json(m))

    # ---- activate / deactivate -----------------------------------------------------------------
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def deactivate(self, request, pk=None):
        m = self._locked(request, pk)
        if Shift.unscoped.filter(cashier=m.user, restaurant=request.tenant, status="open").exists():
            raise serializers.ValidationError({"detail": "This person has an open cashier shift. Ask them to close it first."})
        if m.is_active:
            m.is_active = False
            m.save(update_fields=["is_active", "updated_at"])
            services.revoke_tokens(m.user)  # sessions end now
            audit("staff.deactivated", actor=request.user, restaurant=request.tenant, obj=m,
                  metadata={"reason": str(request.data.get("reason", ""))[:300]}, request=request)
            from apps.notifications.services import queue_email

            queue_email("account_deactivated", m.user.email, {"name": m.user.full_name}, restaurant=request.tenant)
        return Response(member_json(m))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def activate(self, request, pk=None):
        m = self._locked(request, pk)
        if not m.is_active:
            m.is_active = True
            m.save(update_fields=["is_active", "updated_at"])
            audit("staff.activated", actor=request.user, restaurant=request.tenant, obj=m, request=request)
            from apps.notifications.services import queue_email

            queue_email("account_activated", m.user.email, {"name": m.user.full_name, "login_url": services.login_url(request.tenant)}, restaurant=request.tenant)
        return Response(member_json(m))

    @action(detail=True, methods=["post"], url_path="resend-invite")
    @transaction.atomic
    def resend_invite(self, request, pk=None):
        """Issue a fresh one-time password-setup link to someone who has not set a password yet."""
        m = self._locked(request, pk)
        if m.user.email_verified:
            raise serializers.ValidationError({"detail": "This person already activated their account."})
        raw = services.issue_setup_token(m.user, request.tenant)
        from apps.notifications.services import queue_email

        queue_email("staff_invitation", m.user.email, {
            "name": m.user.full_name, "email": m.user.email, "role_label": Role(m.role).label,
            "setup_url": services.setup_url(request.tenant, raw), "login_url": services.login_url(request.tenant)}, restaurant=request.tenant)
        audit("staff.invitation_resent", actor=request.user, restaurant=request.tenant, obj=m, request=request)
        return Response({"success": True})

    # ---- activity review -----------------------------------------------------------------------
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        m = self.get_object()  # scoped: managers only see staff of their own branches
        if ROLE_LEVEL[Role(m.role)] < ROLE_LEVEL[effective_role(request)]:
            raise NotFound()  # nobody reviews someone above them
        logs = (AuditLog.objects.filter(actor=m.user, restaurant=request.tenant).order_by("-created_at")[:50])
        return Response([{"action": a.action, "object_type": a.object_type, "object_id": a.object_id, "created_at": a.created_at} for a in logs])

