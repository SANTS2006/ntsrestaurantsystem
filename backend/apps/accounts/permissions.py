"""Backend authorization services and DRF permission classes.

The role is NEVER read from the token or the client: it is resolved server-side on every request
from the Membership that matches the host-resolved tenant.
"""
from rest_framework.permissions import BasePermission

from .models import BRANCH_SCOPED_ROLES, ROLE_LEVEL, Role


def get_membership(request):
    """Active membership of request.user in request.tenant (cached per request), else None."""
    if hasattr(request, "_membership_cache"):
        return request._membership_cache
    membership = None
    tenant = getattr(request, "tenant", None)
    user = request.user
    if tenant is not None and user and user.is_authenticated:
        membership = user.memberships.filter(restaurant=tenant, is_active=True).first()
    request._membership_cache = membership
    return membership


def effective_role(request):
    user = request.user
    if user and user.is_authenticated and user.is_platform_admin:
        return Role.PLATFORM_ADMIN
    m = get_membership(request)
    return m.role if m else None


def role_level(request):
    role = effective_role(request)
    return ROLE_LEVEL[role] if role else 99


def accessible_branch_ids(request):
    """Branch ids the caller may touch inside the current tenant. Empty set = none."""
    from apps.tenants.models import Branch

    tenant = getattr(request, "tenant", None)
    role = effective_role(request)
    if tenant is None or role is None:
        return set()
    if role in (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN):
        return set(Branch.unscoped.filter(restaurant=tenant).values_list("id", flat=True))
    if role in BRANCH_SCOPED_ROLES:
        return set(get_membership(request).branches.filter(restaurant=tenant).values_list("id", flat=True))
    return set()


def can_assign_role(actor_role, target_role) -> bool:
    """Strictly-higher rule: nobody can grant their own level or above; customers are never assigned."""
    if actor_role is None or target_role in (Role.PLATFORM_ADMIN, Role.CUSTOMER):
        return False
    return ROLE_LEVEL[actor_role] < ROLE_LEVEL[target_role]


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_platform_admin and u.is_active)


class IsPlatformAdminOnPlatformHost(IsPlatformAdmin):
    """Platform administration is only served on the platform's own hostname."""

    def has_permission(self, request, view):
        return bool(getattr(request, "is_platform", False)) and super().has_permission(request, view)


def min_role(max_level, *, name=None):
    """Permission factory: caller's level must be <= max_level (1 = most privileged)."""

    class _MinRole(BasePermission):
        def has_permission(self, request, view):
            # Role-gated resources are tenant resources: they are never served on the platform host.
            return bool(request.user and request.user.is_authenticated and getattr(request, "tenant", None) is not None
                        and role_level(request) <= max_level)

    _MinRole.__name__ = name or f"MinRoleLevel{max_level}"
    return _MinRole


IsRestaurantAdminOrAbove = min_role(ROLE_LEVEL[Role.RESTAURANT_ADMIN], name="IsRestaurantAdminOrAbove")
IsManagerOrAbove = min_role(ROLE_LEVEL[Role.MANAGER], name="IsManagerOrAbove")
IsCashierOrAbove = min_role(ROLE_LEVEL[Role.CASHIER], name="IsCashierOrAbove")
IsStaff = min_role(ROLE_LEVEL[Role.KITCHEN], name="IsStaff")


class IsCustomerOfTenant(BasePermission):
    def has_permission(self, request, view):
        return effective_role(request) == Role.CUSTOMER


class BranchScopedQuerysetMixin:
    """Restrict a viewset's queryset to the caller's tenant and branches (prevents IDOR / cross-branch leaks)."""

    branch_field = "branch_id"

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = self.request.tenant
        if tenant is None:
            return qs.none()
        return qs.filter(restaurant=tenant, **{f"{self.branch_field}__in": accessible_branch_ids(self.request)})
