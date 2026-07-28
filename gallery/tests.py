from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from .models import GalleryImage


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.InMemoryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class StorageAgnosticGalleryTests(TestCase):
    def test_resize_and_delete_do_not_require_a_filesystem_path(self):
        source = BytesIO()
        Image.new("RGB", (1000, 900), color=(100, 50, 25)).save(
            source,
            format="PNG",
        )
        upload = SimpleUploadedFile(
            "large.png",
            source.getvalue(),
            content_type="image/png",
        )

        image = GalleryImage.objects.create(
            image=upload,
            category="salon",
            caption="Storage-independent",
        )
        image.refresh_from_db()
        with default_storage.open(image.image.name, "rb") as stored:
            resized = Image.open(stored)
            self.assertLessEqual(resized.width, 800)
            self.assertLessEqual(resized.height, 800)

        stored_name = image.image.name
        image.delete()
        self.assertFalse(default_storage.exists(stored_name))
