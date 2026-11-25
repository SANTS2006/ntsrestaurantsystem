import csv

from django.http import HttpResponse
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework import generics, serializers

from apps.accounts.permissions import IsManagerOrAbove, IsPlatformAdminOnPlatformHost, IsRestaurantAdminOrAbove, accessible_branch_ids
from apps.core.models import AuditLog, audit
from apps.core.pagination import StandardPagination

from . import finance, services


def _scope(request):
    """Branches the caller may report on. An explicit ?branch= outside their scope is simply 'not found'."""
    allowed = accessible_branch_ids(request)
    b = request.query_params.get("branch", "")
    if b:
        if not b.isdigit() or int(b) not in allowed:
            raise NotFound()
        return {int(b)}
    return allowed


class BranchReportView(services.TenantTimezoneMixin, APIView):
    """Manager: their branches. Restaurant admin: all branches, with a per-branch comparison."""

    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        start, end = services.parse_range(request.query_params)
        group = request.query_params.get("group", "day")
        if group not in ("day", "week", "month"):
            raise ValidationError({"group": "Use day, week or month."})
        return Response(services.build_report(request.tenant, _scope(request), start, end, group))


class ExportView(services.TenantTimezoneMixin, APIView):
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        kind = request.query_params.get("type", "orders")
        if kind not in ("orders", "payments"):
            raise ValidationError({"type": "Use orders or payments."})
        start, end = services.parse_range(request.query_params)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{kind}-{start}-to-{end}.csv"'
        w = csv.writer(resp)
        for row in services.export_rows(kind, request.tenant, _scope(request), start, end):
            w.writerow([services.safe_cell(c) for c in row])
        audit("report.exported", actor=request.user, restaurant=request.tenant, metadata={"type": kind, "from": str(start), "to": str(end)}, request=request)
        return resp


class FinanceReportView(services.TenantTimezoneMixin, APIView):
    """Restaurant-wide financial summary: restaurant administrators only (it includes payroll)."""

    permission_classes = [IsRestaurantAdminOrAbove]

    def get(self, request):
        start, end = services.parse_range(request.query_params)
        return Response(finance.financial_report(request.tenant, start, end))


class FinanceExportView(services.TenantTimezoneMixin, APIView):
    permission_classes = [IsRestaurantAdminOrAbove]

    def get(self, request):
        start, end = services.parse_range(request.query_params)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="financial-summary-{start}-to-{end}.csv"'
        w = csv.writer(resp)
        for row in finance.finance_rows(request.tenant, start, end):
            w.writerow([services.safe_cell(c) for c in row])
        audit("report.exported", actor=request.user, restaurant=request.tenant, metadata={"type": "financial", "from": str(start), "to": str(end)}, request=request)
        return resp


class AnalyticsView(services.TenantTimezoneMixin, APIView):
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        start, end = services.parse_range(request.query_params)
        return Response(finance.analytics(request.tenant, _scope(request), start, end))


class TenantAuditSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "created_at", "action", "actor", "object_type", "object_id", "metadata"]  # no IP addresses for tenant admins

    def get_actor(self, o):
        return (o.actor.full_name or o.actor.email) if o.actor_id else None


class TenantAuditView(services.TenantTimezoneMixin, generics.ListAPIView):
    """The restaurant's own audit trail (never other restaurants' or platform-level entries)."""

    permission_classes = [IsRestaurantAdminOrAbove]
    serializer_class = TenantAuditSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = AuditLog.objects.filter(restaurant=self.request.tenant).select_related("actor").order_by("-created_at", "-id")
        p = self.request.query_params
        if p.get("action"):
            qs = qs.filter(action__startswith=p["action"][:100])
        if p.get("actor", "").isdigit():
            qs = qs.filter(actor_id=int(p["actor"]))
        for key, lookup in (("from", "created_at__date__gte"), ("to", "created_at__date__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lookup: services.date.fromisoformat(p[key])})
                except ValueError:
                    raise ValidationError({key: "Use the format YYYY-MM-DD."})
        return qs


class PlatformReportView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        start, end = services.parse_range(request.query_params)
        return Response(finance.platform_report(start, end))
