from django.core.management.base import BaseCommand

from api.cutover import validate_bundle, verify_against_current


class Command(BaseCommand):
    help = "Verify cutover bundle checksums, optionally against the current target."

    def add_arguments(self, parser):
        parser.add_argument("bundle", help="Path to the cutover ZIP archive.")
        parser.add_argument(
            "--against-current",
            action="store_true",
            help="Also compare all database records and media with the current environment.",
        )

    def handle(self, *args, **options):
        if options["against_current"]:
            manifest = verify_against_current(options["bundle"])
            message = "Bundle exactly matches the current database and media."
        else:
            manifest = validate_bundle(options["bundle"])
            message = "Bundle contents and checksums are valid."

        self.stdout.write(
            self.style.SUCCESS(
                f"{message} {sum(manifest['models'].values())} records and "
                f"{len(manifest['media'])} media files verified."
            )
        )
