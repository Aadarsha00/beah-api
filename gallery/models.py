from django.db import models
from PIL import Image
import os


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

        # Resize image if it's too large
        if self.image:
            img = Image.open(self.image.path)
            if img.height > 800 or img.width > 800:
                img.thumbnail((800, 800))
                img.save(self.image.path)

    def delete(self, *args, **kwargs):
        # Delete the image file when the model instance is deleted
        if self.image:
            if os.path.isfile(self.image.path):
                os.remove(self.image.path)
        super().delete(*args, **kwargs)
