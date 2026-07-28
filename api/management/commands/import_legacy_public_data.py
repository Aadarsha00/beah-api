from decimal import Decimal
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

import requests
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from blog.models import BlogPost
from gallery.models import GalleryImage
from services.models import Service


DEFAULT_SOURCE_URL = "https://api.beautifulbrowsandhenna.com"
DEFAULT_AUTHOR_EMAIL = "admin@beautifulbrowsandhenna.com"
MAX_MEDIA_BYTES = 10 * 1024 * 1024


class Command(BaseCommand):
    help = (
        "Import services, published blog posts, gallery entries, and their media "
        "from the legacy public API."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
        parser.add_argument("--author-email", default=DEFAULT_AUTHOR_EMAIL)
        parser.add_argument(
            "--refresh-media",
            action="store_true",
            help="Download media again even when a local file already exists.",
        )

    def handle(self, *args, **options):
        self.source_url = options["source_url"].rstrip("/")
        self.source_origin = self._origin(self.source_url)
        self.refresh_media = options["refresh_media"]
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "BeautifulBrowsLegacyImporter/1.0"}
        )

        author = self._get_blog_author(options["author_email"])

        with transaction.atomic():
            service_count = self._import_services()
            blog_count = self._import_blog_posts(author)
            gallery_count = self._import_gallery()

        self.stdout.write(
            self.style.SUCCESS(
                "Imported "
                f"{service_count} services, "
                f"{blog_count} blog posts, and "
                f"{gallery_count} gallery images."
            )
        )

    def _get_blog_author(self, email):
        User = get_user_model()
        author = User.objects.filter(email__iexact=email).first()
        if author:
            return author

        author = User.objects.create_user(
            email=email,
            password=None,
            first_name="Legacy",
            last_name="Author",
            phone_number="",
            is_active=True,
        )
        author.set_unusable_password()
        author.save(update_fields=["password"])
        self.stdout.write(f"Created local blog author {email}.")
        return author

    def _import_services(self):
        count = 0
        for summary in self._get_collection("/api/services/"):
            item = self._get_json(f"/api/services/{summary['id']}/")
            service, _ = Service.objects.update_or_create(
                id=item["id"],
                defaults={
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "price": Decimal(item["price"]),
                    "category": item["category"],
                    "duration_minutes": item.get("duration_minutes", 30),
                    "is_active": item.get("is_active", True),
                },
            )
            self._restore_timestamps(service, item)
            count += 1
        return count

    def _import_blog_posts(self, author):
        count = 0
        for summary in self._get_collection("/api/blog/?is_published=true"):
            item = self._get_json(f"/api/blog/{summary['slug']}/")
            image_name = self._download_media(item.get("featured_image_url"))
            post, _ = BlogPost.objects.update_or_create(
                id=item["id"],
                defaults={
                    "title": item["title"],
                    "slug": item["slug"],
                    "author": author,
                    "content": item.get("content", ""),
                    "excerpt": item.get("excerpt", ""),
                    "category": item["category"],
                    "featured_image": image_name or None,
                    "meta_description": item.get("meta_description", ""),
                    "keywords": item.get("keywords", ""),
                    "is_published": item.get("is_published", True),
                    "is_featured": item.get("is_featured", False),
                    "views_count": item.get("views_count", 0),
                    "published_at": self._datetime(item.get("published_at")),
                },
            )
            self._restore_timestamps(post, item)
            count += 1
        return count

    def _import_gallery(self):
        count = 0
        for summary in self._get_collection("/api/gallery/?is_active=true"):
            item = self._get_json(f"/api/gallery/{summary['id']}/")
            image_name = self._download_media(item.get("image_url"))
            if not image_name:
                raise CommandError(
                    f"Gallery record {item['id']} does not contain an image URL."
                )

            image, _ = GalleryImage.objects.update_or_create(
                id=item["id"],
                defaults={
                    "image": image_name,
                    "caption": item.get("caption", ""),
                    "category": item["category"],
                    "is_featured": item.get("is_featured", False),
                    "is_active": item.get("is_active", True),
                    "order": item.get("order", 0),
                },
            )
            self._restore_timestamps(image, item)
            count += 1
        return count

    def _get_collection(self, path):
        next_url = self._url(path)
        while next_url:
            self._require_source_origin(next_url)
            payload = self._request_json(next_url)
            if isinstance(payload, list):
                yield from payload
                return
            if not isinstance(payload, dict) or "results" not in payload:
                raise CommandError(f"Unexpected collection response from {next_url}.")
            yield from payload["results"]
            next_url = payload.get("next")

    def _get_json(self, path):
        return self._request_json(self._url(path))

    def _request_json(self, url):
        try:
            response = self.session.get(url, timeout=(10, 30))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"Could not read {url}: {exc}") from exc

    def _download_media(self, url):
        if not url:
            return ""

        self._require_source_origin(url)
        parsed = urlparse(url)
        marker = "/media/"
        if marker not in parsed.path:
            raise CommandError(f"Media URL is outside /media/: {url}")

        name = unquote(parsed.path.split(marker, 1)[1]).lstrip("/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise CommandError(f"Unsafe media path in {url}")

        storage_name = path.as_posix()
        if default_storage.exists(storage_name):
            if not self.refresh_media:
                return storage_name
            default_storage.delete(storage_name)

        try:
            response = self.session.get(url, stream=True, timeout=(10, 60))
            response.raise_for_status()
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            if content_length > MAX_MEDIA_BYTES:
                raise CommandError(f"Media file exceeds 10 MB: {url}")

            data = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_MEDIA_BYTES:
                    raise CommandError(f"Media file exceeds 10 MB: {url}")
        except requests.RequestException as exc:
            raise CommandError(f"Could not download {url}: {exc}") from exc

        return default_storage.save(storage_name, ContentFile(bytes(data)))

    def _restore_timestamps(self, instance, item):
        timestamps = {}
        for field in ("created_at", "updated_at"):
            value = self._datetime(item.get(field))
            if value:
                timestamps[field] = value
        if timestamps:
            type(instance).objects.filter(pk=instance.pk).update(**timestamps)

    def _datetime(self, value):
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            raise CommandError(f"Invalid datetime received from legacy API: {value}")
        return parsed

    def _url(self, path):
        return urljoin(f"{self.source_url}/", path.lstrip("/"))

    def _require_source_origin(self, url):
        if self._origin(url) != self.source_origin:
            raise CommandError(f"Refusing to request a different origin: {url}")

    @staticmethod
    def _origin(url):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CommandError(f"Invalid HTTP(S) source URL: {url}")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
