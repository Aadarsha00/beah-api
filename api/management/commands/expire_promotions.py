"""
Management command to automatically expire promotions
Usage: python manage.py expire_promotions

"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import Promotion


class Command(BaseCommand):
    help = "Automatically expire promotions that have passed their end date"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be expired without actually expiring them",
        )

    def handle(self, *args, **options):
        today = timezone.now().date()

        # Find active promotions that have expired
        expired_promotions = Promotion.objects.filter(
            is_active=True, end_date__lt=today
        )

        count = expired_promotions.count()

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: Would expire {count} promotions")
            )
            for promotion in expired_promotions:
                self.stdout.write(
                    f"  - {promotion.title} (ended: {promotion.end_date})"
                )
        else:
            if count > 0:
                expired_promotions.update(is_active=False)
                self.stdout.write(
                    self.style.SUCCESS(f"Successfully expired {count} promotions")
                )
                for promotion in expired_promotions:
                    self.stdout.write(f"  - {promotion.title}")
            else:
                self.stdout.write(
                    self.style.SUCCESS("No promotions need to be expired")
                )
