import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from blog.models import BlogPost
from gallery.models import GalleryImage
from services.models import Service


class FakeResponse:
    def __init__(self, *, payload=None, content=b""):
        self.payload = payload
        self.content = content
        self.headers = {"Content-Length": str(len(content))}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]


class FakeLegacySession:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}

    def get(self, url, **kwargs):
        return self.responses[url]


class LegacyPublicDataImportTests(TestCase):
    source = "https://legacy.example.com"
    timestamp = "2026-01-11T14:13:58.209313Z"

    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)

        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), color="gold").save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        self.responses = {
            f"{self.source}/api/services/": FakeResponse(
                payload={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [{"id": 10}],
                }
            ),
            f"{self.source}/api/services/10/": FakeResponse(
                payload={
                    "id": 10,
                    "name": "Eyebrow Tinting",
                    "description": "Tinted brows.",
                    "price": "20.00",
                    "category": "lashes",
                    "duration_minutes": 20,
                    "is_active": True,
                    "created_at": self.timestamp,
                    "updated_at": self.timestamp,
                }
            ),
            f"{self.source}/api/blog/?is_published=true": FakeResponse(
                payload={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [{"id": 1, "slug": "legacy-post"}],
                }
            ),
            f"{self.source}/api/blog/legacy-post/": FakeResponse(
                payload={
                    "id": 1,
                    "title": "Legacy post",
                    "slug": "legacy-post",
                    "content": "Full content",
                    "excerpt": "Full content",
                    "category": "threading",
                    "featured_image_url": (
                        f"{self.source}/media/blog/2026/01/legacy.png"
                    ),
                    "meta_description": "",
                    "keywords": "",
                    "is_published": True,
                    "is_featured": False,
                    "views_count": 4,
                    "created_at": self.timestamp,
                    "updated_at": self.timestamp,
                    "published_at": self.timestamp,
                }
            ),
            f"{self.source}/api/gallery/?is_active=true": FakeResponse(
                payload={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [{"id": 1}],
                }
            ),
            f"{self.source}/api/gallery/1/": FakeResponse(
                payload={
                    "id": 1,
                    "image_url": (
                        f"{self.source}/media/gallery/2026/01/legacy.png"
                    ),
                    "caption": "Legacy image",
                    "category": "brows",
                    "is_featured": True,
                    "is_active": True,
                    "order": 2,
                    "created_at": self.timestamp,
                    "updated_at": self.timestamp,
                }
            ),
            f"{self.source}/media/blog/2026/01/legacy.png": FakeResponse(
                content=image_bytes
            ),
            f"{self.source}/media/gallery/2026/01/legacy.png": FakeResponse(
                content=image_bytes
            ),
        }

    def test_imports_public_data_and_is_safe_to_rerun(self):
        with override_settings(MEDIA_ROOT=self.media_directory.name):
            session = FakeLegacySession(self.responses)
            with patch(
                "api.management.commands.import_legacy_public_data.requests.Session",
                return_value=session,
            ):
                call_command(
                    "import_legacy_public_data",
                    source_url=self.source,
                    verbosity=0,
                )
                call_command(
                    "import_legacy_public_data",
                    source_url=self.source,
                    verbosity=0,
                )

        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(BlogPost.objects.count(), 1)
        self.assertEqual(GalleryImage.objects.count(), 1)

        service = Service.objects.get(pk=10)
        self.assertEqual(service.name, "Eyebrow Tinting")
        self.assertEqual(str(service.price), "20.00")

        post = BlogPost.objects.get(pk=1)
        self.assertEqual(post.slug, "legacy-post")
        self.assertEqual(post.content, "Full content")
        self.assertEqual(post.featured_image.name, "blog/2026/01/legacy.png")

        gallery_image = GalleryImage.objects.get(pk=1)
        self.assertEqual(gallery_image.image.name, "gallery/2026/01/legacy.png")
        self.assertEqual(gallery_image.order, 2)

        author = get_user_model().objects.get(
            email="admin@beautifulbrowsandhenna.com"
        )
        self.assertFalse(author.has_usable_password())
