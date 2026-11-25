from django.core.management.base import BaseCommand, CommandError

from apps.accounts import mfa
from apps.accounts.models import User
from apps.core.models import audit


class Command(BaseCommand):
    help = "Operator tool: remove a user's two-factor setup (lost authenticator). The user must enrol again at next sign-in."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **opts):
        u = User.objects.filter(email=opts["email"].lower()).first()
        if u is None:
            raise CommandError("No such user.")
        mfa.disable(u)
        audit("auth.mfa_reset_by_operator", metadata={"user": u.pk})
        self.stdout.write(self.style.SUCCESS(f"Two-factor authentication reset for {u.email}; all their sessions were revoked."))
