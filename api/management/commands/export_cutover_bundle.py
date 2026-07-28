from django.core.management.base import BaseCommand

from api.cutover import export_bundle


class Command(BaseCommand):
    help = (
        "Export all business records and all media into a confidential, "
        "checksummed cutover ZIP without changing source data."
    )

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path for the new cutover ZIP archive.")
        parser.add_argument(
            "--maintenance-mode-confirmed",
            action="store_true",
            help=(
                "Required acknowledgement that all application writes are stopped "
                "for the complete database-and-media export."
            ),
        )

    def handle(self, *args, **options):
        manifest = export_bundle(
            options["output"],
            maintenance_confirmed=options["maintenance_mode_confirmed"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Cutover bundle created and verified: "
                f"{options['output']} "
                f"({sum(manifest['models'].values())} records, "
                f"{len(manifest['media'])} media files)"
            )
        )
        self.stdout.write(self.style.WARNING(manifest["confidential"]))
