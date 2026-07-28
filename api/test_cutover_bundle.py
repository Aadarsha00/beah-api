import json
import tempfile
import zipfile
from datetime import time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from PIL import Image
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from appointments.models import Appointment, BookingDayLock
from blog.models import BlogPost
from gallery.models import GalleryImage
from services.models import Service

from .cutover import (
    DATA_MEMBER,
    MANIFEST_MEMBER,
    export_bundle,
    iter_storage_files,
    restore_bundle,
    validate_bundle,
    verify_against_current,
)
from .models import AdminNote, ContactMessage, Promotion

User = get_user_model()


class CutoverBundleTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            SEND_CONTACT_EMAILS=False,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.user = User.objects.create_user(
            id=41,
            email="preserved@example.com",
            password="source-password-that-is-never-exported-as-plaintext",
            first_name="Preserved",
            last_name="Customer",
            phone_number="+14105550141",
            is_active=True,
        )
        self.password_hash = self.user.password
        self.group = Group.objects.create(id=31, name="Preserved group")
        self.group.permissions.add(Permission.objects.order_by("pk").first())
        self.service = Service.objects.create(
            id=51,
            name="Preserved service",
            description="Cutover test",
            price=Decimal("25.00"),
            category="threading",
            duration_minutes=30,
        )
        self.appointment = Appointment.objects.create(
            id=61,
            client=self.user,
            client_name=self.user.get_full_name(),
            client_email=self.user.email,
            client_phone=self.user.phone_number,
            service=self.service,
            appointment_date=timezone.localdate() + timedelta(days=10),
            appointment_time=time(11, 0),
            duration_minutes=30,
            total_amount=Decimal("25.00"),
        )
        BookingDayLock.objects.create(date=self.appointment.appointment_date)
        LogEntry.objects.log_action(
            user_id=self.user.pk,
            content_type_id=ContentType.objects.get_for_model(Service).pk,
            object_id=str(self.service.pk),
            object_repr=self.service.name,
            action_flag=ADDITION,
            change_message="Created before cutover",
        )
        self.post = BlogPost.objects.create(
            id=71,
            title="Preserved post",
            slug="preserved-post",
            author=self.user,
            content="Content that must survive the storage-engine change.",
            category="news",
            is_published=True,
        )
        self.promotion = Promotion.objects.create(
            id=81,
            title="Preserved promotion",
            description="Promotion details",
            discount_percentage=Decimal("10.00"),
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
        )
        self.promotion.applicable_services.add(self.service)
        ContactMessage.objects.create(
            id=91,
            name="Contact",
            email="contact@example.com",
            subject="Preserve this",
            message="This business message must be restored.",
        )
        AdminNote.objects.create(
            id=101,
            title="Preserved note",
            content="Internal business note for the cutover test.",
            created_by=self.user,
        )

        self.media_bytes = self._png_bytes()
        media_name = default_storage.save(
            "gallery/2026/07/preserved.png",
            ContentFile(self.media_bytes),
        )
        self.gallery_image = GalleryImage.objects.create(
            id=111,
            image=media_name,
            caption="Preserved image",
            category="salon",
        )
        self.bundle_path = Path(self.temporary_directory.name) / "cutover.zip"

    @staticmethod
    def _png_bytes():
        output = BytesIO()
        Image.new("RGB", (4, 4), color=(120, 60, 30)).save(output, format="PNG")
        return output.getvalue()

    def _clear_test_target(self):
        LogEntry.objects.all().delete()
        Appointment.objects.all().delete()
        BookingDayLock.objects.all().delete()
        BlogPost.objects.all().delete()
        GalleryImage.objects.all().delete()
        Promotion.objects.all().delete()
        ContactMessage.objects.all().delete()
        AdminNote.objects.all().delete()
        Service.objects.all().delete()
        Group.objects.all().delete()
        User.objects.all().delete()
        for media_name in list(iter_storage_files()):
            default_storage.delete(media_name)

    def test_restore_preserves_ids_hashes_relationships_and_media_bytes(self):
        source_manifest = export_bundle(
            self.bundle_path,
            maintenance_confirmed=True,
        )
        validate_bundle(self.bundle_path)

        self._clear_test_target()
        restored_manifest = restore_bundle(
            self.bundle_path,
            allow_non_mysql=True,
        )

        self.assertEqual(restored_manifest["models"], source_manifest["models"])
        restored_user = User.objects.get(pk=41)
        restored_appointment = Appointment.objects.get(pk=61)
        restored_promotion = Promotion.objects.get(pk=81)
        restored_gallery = GalleryImage.objects.get(pk=111)
        self.assertEqual(restored_user.password, self.password_hash)
        self.assertTrue(restored_user.check_password(
            "source-password-that-is-never-exported-as-plaintext"
        ))
        self.assertEqual(restored_appointment.client_id, 41)
        self.assertEqual(restored_appointment.service_id, 51)
        self.assertEqual(Group.objects.get(pk=31).permissions.count(), 1)
        self.assertEqual(LogEntry.objects.get().user_id, 41)
        self.assertEqual(
            list(restored_promotion.applicable_services.values_list("pk", flat=True)),
            [51],
        )
        with default_storage.open(restored_gallery.image.name, "rb") as media_file:
            self.assertEqual(media_file.read(), self.media_bytes)
        verify_against_current(self.bundle_path)

    def test_restore_refuses_non_empty_database_without_changing_it(self):
        export_bundle(self.bundle_path, maintenance_confirmed=True)
        original_user_count = User.objects.count()

        with self.assertRaisesRegex(CommandError, "non-empty target database"):
            restore_bundle(self.bundle_path, allow_non_mysql=True)

        self.assertEqual(User.objects.count(), original_user_count)
        self.assertTrue(User.objects.filter(pk=41).exists())

    def test_tampered_database_member_fails_checksum_before_restore(self):
        export_bundle(self.bundle_path, maintenance_confirmed=True)
        tampered_path = Path(self.temporary_directory.name) / "tampered.zip"
        with zipfile.ZipFile(self.bundle_path, "r") as source:
            with zipfile.ZipFile(tampered_path, "w") as target:
                for item in source.infolist():
                    value = source.read(item.filename)
                    if item.filename == DATA_MEMBER:
                        fixture = json.loads(value)
                        fixture[0]["fields"]["email"] = "tampered@example.com"
                        value = json.dumps(fixture).encode("utf-8")
                    target.writestr(item, value)

        with self.assertRaisesRegex(CommandError, "checksum verification failed"):
            validate_bundle(tampered_path)

    def test_export_refuses_to_overwrite_an_existing_bundle(self):
        export_bundle(self.bundle_path, maintenance_confirmed=True)
        with self.assertRaisesRegex(CommandError, "Refusing to overwrite"):
            export_bundle(self.bundle_path, maintenance_confirmed=True)

        with zipfile.ZipFile(self.bundle_path) as archive:
            self.assertIn(MANIFEST_MEMBER, archive.namelist())

    def test_export_requires_explicit_maintenance_confirmation(self):
        with self.assertRaisesRegex(CommandError, "requires maintenance mode"):
            export_bundle(self.bundle_path)

    def test_restore_refuses_any_existing_target_media(self):
        export_bundle(self.bundle_path, maintenance_confirmed=True)
        self._clear_test_target()
        default_storage.save("orphan.txt", ContentFile(b"do not overwrite"))

        with self.assertRaisesRegex(CommandError, "non-empty target media"):
            restore_bundle(self.bundle_path, allow_non_mysql=True)

        self.assertTrue(default_storage.exists("orphan.txt"))
        self.assertEqual(User.objects.count(), 0)

    def test_verify_against_current_rejects_extra_media(self):
        export_bundle(self.bundle_path, maintenance_confirmed=True)
        default_storage.save("extra.txt", ContentFile(b"not in manifest"))

        with self.assertRaisesRegex(CommandError, "extra.*extra.txt"):
            verify_against_current(self.bundle_path)
