"""Real-time staff notifications over Django Channels.

* Groups are named per restaurant AND branch, so an event can only reach staff of that exact branch.
* The WebSocket consumer authenticates with a JWT sent as the first message (never in the URL, which ends up in logs),
  resolves the restaurant from the validated Host header (never from the client), and re-checks the role, the
  membership and token revocation before joining anything.
* Publishing is best-effort: if the channel layer is down the HTTP request still succeeds and staff fall back to polling.
"""
import asyncio
import logging

from asgiref.sync import async_to_sync, sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction

log = logging.getLogger(__name__)
ALLOWED_ROLES = {"platform_admin", "restaurant_admin", "manager", "cashier"}  # staff who handle the till / requests


def group_name(restaurant_id, branch_id):
    return f"staff.r{restaurant_id}.b{branch_id}"


def _send(restaurant_id, branch_id, payload):
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(group_name(restaurant_id, branch_id), {"type": "staff.event", "payload": payload})
    except Exception:  # noqa: BLE001: never fail a customer request because live push is unavailable
        log.exception("realtime publish failed")


def notify_branch(restaurant_id, branch_id, payload):
    """Publish after the surrounding transaction commits, so staff are never told about something that rolled back."""
    transaction.on_commit(lambda: _send(restaurant_id, branch_id, payload))


def authenticate_ws(token, tenant):
    """Sync helper: returns (user, branch_ids) or None. Mirrors the HTTP authorisation rules."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.models import Membership, Role, User
    from apps.tenants.models import Branch

    try:
        t = AccessToken(token)
        user = User.objects.get(pk=t["user_id"], is_active=True)
    except (TokenError, User.DoesNotExist, KeyError):
        return None
    if t.get("tv") != user.token_version:  # revoked (password change, deactivation...)
        return None
    if user.is_platform_admin:
        role = Role.PLATFORM_ADMIN
        m = None
    else:
        m = Membership.objects.filter(user=user, restaurant=tenant, is_active=True).first()
        if m is None:
            return None
        role = m.role
    if role not in ALLOWED_ROLES:
        return None
    if role in (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN):
        ids = list(Branch.unscoped.filter(restaurant=tenant).values_list("pk", flat=True))
    else:
        ids = list(m.branches.filter(restaurant=tenant).values_list("pk", flat=True))
    return user, ids


def resolve_tenant(host, slug=None):
    from apps.core.middleware import resolve_host
    from apps.tenants.models import RESERVED_SLUGS, Restaurant

    is_platform, restaurant, found = resolve_host(host)
    if not found:
        return None
    if is_platform:
        if not slug or slug in RESERVED_SLUGS:
            return None
        restaurant = Restaurant.unscoped_objects.filter(slug=slug).first()
    elif slug:  # a custom domain has no slug in its path
        return None
    if restaurant is None or restaurant.status != "active":
        return None
    return restaurant


class StaffConsumer(AsyncJsonWebsocketConsumer):
    authed = False

    async def connect(self):
        host = dict(self.scope.get("headers", [])).get(b"host", b"").decode()
        self.tenant = await sync_to_async(resolve_tenant)(host, self.scope.get("url_route", {}).get("kwargs", {}).get("slug"))
        if self.tenant is None:
            await self.close(code=4404)
            return
        self.groups_joined = []
        await self.accept()
        self._timeout = asyncio.create_task(self._auth_deadline())

    async def _auth_deadline(self):
        await asyncio.sleep(settings.WS_AUTH_TIMEOUT_SECONDS)
        if not self.authed:
            await self.close(code=4401)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if not self.authed:
            if kind != "auth" or not isinstance(content.get("token"), str):
                await self.close(code=4401)
                return
            result = await sync_to_async(authenticate_ws)(content["token"], self.tenant)
            if result is None:
                await self.close(code=4403)
                return
            self.user, branch_ids = result
            self.authed = True
            self._timeout.cancel()
            for b in branch_ids:
                name = group_name(self.tenant.pk, b)
                await self.channel_layer.group_add(name, self.channel_name)
                self.groups_joined.append(name)
            await self.send_json({"type": "ready", "branches": branch_ids})
        elif kind == "ping":
            await self.send_json({"type": "pong"})

    async def staff_event(self, event):
        await self.send_json(event["payload"])

    async def disconnect(self, code):
        if getattr(self, "_timeout", None):
            self._timeout.cancel()
        for name in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(name, self.channel_name)
