from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a new backup encryption key (a Fernet key). Put it in BACKUP_ENCRYPTION_KEY and keep a copy somewhere safe: without it every backup is unreadable."

    def handle(self, *args, **opts):
        self.stdout.write(Fernet.generate_key().decode())
