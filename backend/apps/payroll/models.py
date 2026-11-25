from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import TenantOwnedModel

EARNING_TYPES = ("allowance", "bonus", "overtime", "other_earning")
DEDUCTION_TYPES = ("deduction", "other_deduction")
COMPONENT_TYPES = EARNING_TYPES + DEDUCTION_TYPES
PAY_METHODS = ("cash", "bank_transfer", "mobile_money", "other")


class PayrollSettings(models.Model):
    """Per-restaurant approval policy. By default nobody can approve payroll they prepared or that is their own pay."""

    restaurant = models.OneToOneField("tenants.Restaurant", on_delete=models.CASCADE, related_name="payroll_settings")
    allow_admin_self_approval = models.BooleanField(default=False)
    # Statutory rules (income tax, pension...) configured by the restaurant administrator; see services.clean_rules.
    tax_rules = models.JSONField(default=list, blank=True)  # lets a sole owner prepare/approve/pay alone (a conscious, audited choice)


class SalaryStructure(TenantOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACTIVE = "active"
        REJECTED = "rejected"
        SUPERSEDED = "superseded"

    class Frequency(models.TextChoices):
        MONTHLY = "monthly"
        BIWEEKLY = "biweekly"
        WEEKLY = "weekly"

    employee = models.ForeignKey("accounts.Membership", on_delete=models.PROTECT, related_name="salary_structures")
    version = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    components = models.JSONField(default=list)  # [{type, name, mode: fixed|percent_of_basic, amount}]
    terms = models.TextField(blank=True, max_length=2000)
    currency = models.CharField(max_length=3)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=300, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "version"], name="uniq_salary_version"),
            models.UniqueConstraint(fields=["employee"], condition=Q(status="active"), name="one_active_structure_per_employee"),
            models.UniqueConstraint(fields=["employee"], condition=Q(status="pending"), name="one_pending_structure_per_employee"),
            models.CheckConstraint(condition=Q(basic_salary__gte=0), name="salary_basic_non_negative"),
        ]


class PayrollPeriod(TenantOwnedModel):
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "year", "month"], name="uniq_payroll_period"),
                       models.CheckConstraint(condition=Q(month__gte=1, month__lte=12), name="payroll_month_range")]

    def __str__(self):
        return f"{self.year}-{self.month:02d}"


class PayrollSequence(models.Model):
    restaurant = models.OneToOneField("tenants.Restaurant", on_delete=models.CASCADE, related_name="+")
    last_number = models.PositiveBigIntegerField(default=0)


class PayrollRecord(TenantOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        SUBMITTED = "submitted"
        APPROVED = "approved"
        PAID = "paid"
        REJECTED = "rejected"
        CANCELLED = "cancelled"

    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name="records")
    employee = models.ForeignKey("accounts.Membership", on_delete=models.PROTECT, related_name="payroll_records")
    branch = models.ForeignKey("tenants.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # null for restaurant-wide roles
    structure = models.ForeignKey(SalaryStructure, on_delete=models.PROTECT, related_name="records")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    currency = models.CharField(max_length=3)

    # Frozen at preparation: later changes to salary structures never alter a finalised record.
    lines = models.JSONField(default=list)          # [{source, type, name, amount}]
    adjustments = models.JSONField(default=list)    # period-specific items the preparer entered
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    total_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_bonuses = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_overtime = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_other_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gross = models.DecimalField(max_digits=12, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net = models.DecimalField(max_digits=12, decimal_places=2)
    total_statutory = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # employee tax/contributions withheld (inside total_deductions)
    employer_contributions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # paid by the restaurant on top of gross

    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    paid_on = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=15, blank=True)
    payment_reference = models.CharField(max_length=80, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-period__year", "-period__month", "employee_id"]
        constraints = [models.UniqueConstraint(fields=["period", "employee"], name="uniq_record_per_period_employee"),
                       models.CheckConstraint(condition=Q(net__gte=0) & Q(gross__gte=0), name="payroll_amounts_non_negative")]
        indexes = [models.Index(fields=["restaurant", "status"])]

    def save(self, *args, **kwargs):
        if self.pk is not None and PayrollRecord.unscoped.filter(pk=self.pk, status="paid").exists():
            raise PermissionError("A paid payroll record cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Payroll records cannot be deleted.")


class SalaryReceipt(TenantOwnedModel):
    """Immutable proof of a salary payment (numbered per restaurant)."""

    record = models.OneToOneField(PayrollRecord, on_delete=models.PROTECT, related_name="receipt")
    number = models.CharField(max_length=30)
    data = models.JSONField()

    class Meta(TenantOwnedModel.Meta):
        constraints = [models.UniqueConstraint(fields=["restaurant", "number"], name="uniq_salary_receipt_number")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Salary receipts are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Salary receipts cannot be deleted.")
