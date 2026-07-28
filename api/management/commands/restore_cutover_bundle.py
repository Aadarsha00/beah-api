from django.core.management.base import BaseCommand

from api.cutover import restore_bundle


class Command(BaseCommand):
    help = (
        "Restore a verified cutover bundle into a freshly migrated, empty MySQL "
        "database and empty media storage."
    )

    def add_arguments(self, parser):
        parser.add_argument("bundle", help="Path to the cutover ZIP archive.")
        parser.add_argument(
            "--allow-non-mysql",
            action="store_true",
            help="Reserved for isolated automated tests; production must use MySQL.",
        )

    def handle(self, *args, **options):
        manifest = restore_bundle(
            options["bundle"],
            allow_non_mysql=options["allow_non_mysql"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Restore completed with matching database and media checksums: "
                f"{sum(manifest['models'].values())} records, "
                f"{len(manifest['media'])} media files."
            )
        )
