from django.db import models
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4


class GalleryImage(models.Model):
    CATEGORY_CHOICES = [
        ("brows", "Eyebrows"),
        ("henna", "Henna Art"),
        ("lashes", "Lashes"),
        ("salon", "Salon"),
    ]

    image = models.ImageField(upload_to="gallery/%Y/%m/")
    caption = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "order", "-created_at"]

    def __str__(self):
        return f"{self.get_category_display()} - {self.caption[:50] if self.caption else 'No caption'}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if not self.image:
            return

        # Use Django's storage API rather than filesystem-only ``.path`` so a
        # persistent mounted volume or a compatible object store can be used.
        storage = self.image.storage
        original_name = self.image.name
        with storage.open(original_name, "rb") as source:
            image = Image.open(source)
            image.load()
            image_format = image.format or "JPEG"

        if image.height <= 800 and image.width <= 800:
            return

        image.thumbnail((800, 800))
        if image_format.upper() in {"JPEG", "JPG"} and image.mode not in {"L", "RGB"}:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format=image_format)

        original_path = PurePosixPath(original_name)
        resized_filename = (
            f"{original_path.stem}-resized-{uuid4().hex}{original_path.suffix}"
        )
        resized_name = (original_path.parent / resized_filename).as_posix()
        saved_name = storage.save(resized_name, ContentFile(output.getvalue()))
        try:
            type(self).objects.filter(pk=self.pk).update(image=saved_name)
            self.image.name = saved_name
        except Exception:
            storage.delete(saved_name)
            raise
        storage.delete(original_name)

    def delete(self, *args, **kwargs):
        storage = self.image.storage if self.image else None
        image_name = self.image.name if self.image else ""
        result = super().delete(*args, **kwargs)
        if storage and image_name:
            storage.delete(image_name)
        return result
