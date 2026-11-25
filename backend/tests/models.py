from django.db import models

from apps.core.tenancy import BranchOwnedModel


class Thing(BranchOwnedModel):
    """Test-only branch-owned model exercising the tenancy base classes."""

    label = models.CharField(max_length=50)
