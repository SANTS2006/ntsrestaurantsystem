"""Who hears about a new website message: the platform's administrators, or the restaurant's administrators and the managers
of the branch the visitor chose."""
import logging

from django.conf import settings

from apps.accounts.models import User
from apps.notifications.inapp import notify_users, staff_at
from apps.notifications.services import queue_email
from apps.tenants.models import PlatformSettings

log = logging.getLogger(__name__)


def team_for(message):
    if message.restaurant_id is None:
        return list(User.objects.filter(is_platform_admin=True, is_active=True))
    if message.branch_id:
        return list(staff_at(message.restaurant, message.branch_id, ("restaurant_admin", "manager")))
    return list(User.objects.filter(memberships__restaurant=message.restaurant, memberships__is_active=True,
                                    memberships__role__in=("restaurant_admin", "manager"), is_active=True).distinct())


def inbox_path(message):
    base = "/admin/messages" if message.restaurant_id is None else "/manage/website-contact"
    return f"{base}?open={message.pk}"


def new_message(message):
    try:
        restaurant = message.restaurant
        notify_users(team_for(message), "contact_message", f"New website message from {message.name}", message.subject, inbox_path(message),
                     restaurant, about=("contact_message", message.pk))
        inbox = restaurant.contact_email if restaurant else (PlatformSettings.load().support_email or settings.BREVO_SENDER_EMAIL)
        if inbox:
            root = restaurant.public_url if restaurant else f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}"
            queue_email("contact_received", inbox, {
                "reference": message.reference, "name": message.name, "email": message.email, "phone": message.phone or "-",
                "subject": message.subject, "message": message.message, "url": root + inbox_path(message)},
                restaurant=restaurant, dedupe_key=f"contact-received:{message.pk}")
    except Exception:  # noqa: BLE001 - the visitor's message is saved; telling the team must never fail it
        log.exception("could not announce a website message")
