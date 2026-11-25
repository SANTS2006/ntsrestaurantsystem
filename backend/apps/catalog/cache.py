"""Tenant-aware cache for the public menu. Keys always include the restaurant id and a per-restaurant
version that is bumped on every catalog write, so availability/price changes show up immediately."""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

MENU_TTL = 60  # safety net (e.g. timed offers expiring); writes invalidate explicitly


def _ver_key(restaurant_id):
    return f"menuver:{restaurant_id}"


def menu_key(restaurant_id, suffix="menu"):
    version = cache.get(_ver_key(restaurant_id))
    if version is None:
        cache.add(_ver_key(restaurant_id), 1, None)
        version = cache.get(_ver_key(restaurant_id), 1)
    return f"{suffix}:{restaurant_id}:{version}"


def bump_menu(restaurant_id):
    try:
        cache.incr(_ver_key(restaurant_id))
    except ValueError:
        cache.set(_ver_key(restaurant_id), 2, None)


def connect_signals():
    from .models import Category, Product, ProductAddon, ProductVariation, Service

    def handler(sender, instance, **kwargs):
        bump_menu(instance.restaurant_id)

    for model in (Category, Product, ProductAddon, ProductVariation, Service):
        post_save.connect(handler, sender=model, weak=False, dispatch_uid=f"menu-bump-save-{model.__name__}")
        post_delete.connect(handler, sender=model, weak=False, dispatch_uid=f"menu-bump-del-{model.__name__}")
