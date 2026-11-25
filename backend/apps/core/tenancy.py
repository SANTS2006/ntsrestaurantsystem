"""Tenant-aware model infrastructure.

Isolation is enforced at the data layer, not in the frontend:

* ``TenantOwnedModel`` gives every record a mandatory ``restaurant`` FK.
* ``BranchOwnedModel`` additionally requires a ``branch`` belonging to that same restaurant.
* The default manager auto-filters by the *current tenant* (a context variable set by the
  request middleware, or by ``tenant_context`` in background jobs / management commands).
* ``unscoped`` is the explicit, greppable escape hatch for platform-level code.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models

_current_tenant: ContextVar = ContextVar("current_tenant", default=None)


def get_current_tenant():
    return _current_tenant.get()


def set_current_tenant(restaurant):
    return _current_tenant.set(restaurant)


def reset_current_tenant(token):
    _current_tenant.reset(token)


@contextmanager
def tenant_context(restaurant):
    """Bind a tenant for the duration of a block (Celery tasks, commands, tests)."""
    token = set_current_tenant(restaurant)
    try:
        yield restaurant
    finally:
        reset_current_tenant(token)


class TenantQuerySet(models.QuerySet):
    def for_restaurant(self, restaurant):
        return self.filter(restaurant=restaurant)

    def for_branches(self, branch_ids):
        """Restrict to the given branch ids (ids come from the backend, never the client)."""
        return self.filter(branch_id__in=list(branch_ids))


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Auto-scopes to the current tenant when one is bound."""

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is not None:
            qs = qs.filter(restaurant=tenant)
        return qs


class UnscopedManager(models.Manager.from_queryset(TenantQuerySet)):
    """Platform-level access across tenants. Use deliberately and only behind platform permissions."""


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantOwnedModel(TimeStampedModel):
    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.PROTECT, related_name="+", db_index=True
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        abstract = True
        base_manager_name = "unscoped"

    def save(self, *args, **kwargs):
        if self.restaurant_id is None:
            tenant = get_current_tenant()
            if tenant is None:
                raise ValidationError("A tenant-owned record requires a restaurant.")
            self.restaurant = tenant
        super().save(*args, **kwargs)


class BranchOwnedModel(TenantOwnedModel):
    branch = models.ForeignKey("tenants.Branch", on_delete=models.PROTECT, related_name="+", db_index=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.restaurant_id is None:
            tenant = get_current_tenant()
            if tenant is None:
                raise ValidationError("A tenant-owned record requires a restaurant.")
            self.restaurant = tenant
        # Defence in depth: a branch can never belong to a different tenant than the record.
        from apps.tenants.models import Branch

        branch_restaurant_id = Branch.unscoped.filter(pk=self.branch_id).values_list("restaurant_id", flat=True).first()
        if branch_restaurant_id != self.restaurant_id:
            raise ValidationError("Branch does not belong to this restaurant.")
        super().save(*args, **kwargs)
