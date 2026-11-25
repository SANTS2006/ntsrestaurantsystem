"""Bootstrap a platform administrator. Credentials come from the environment, never from source code.

    $env:PLATFORM_ADMIN_EMAIL="you@example.com"; $env:PLATFORM_ADMIN_PASSWORD="..."
    python manage.py create_platform_admin
"""
import os

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create a platform administrator from PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD."

    def handle(self, *args, **options):
        email = os.environ.get("PLATFORM_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("PLATFORM_ADMIN_PASSWORD", "")
        if not email or not password:
            raise CommandError("Set PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD.")
        if User.objects.filter(email=email).exists():
            raise CommandError("A user with that email already exists.")
        validate_password(password, User(email=email))
        User.objects.create_user(email, password, full_name="Platform Administrator", is_platform_admin=True,
                                 email_verified=True, is_staff=True)
        self.stdout.write(self.style.SUCCESS(f"Platform administrator {email} created."))
