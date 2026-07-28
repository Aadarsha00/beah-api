from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.urls import reverse

User = get_user_model()


class BlogPost(models.Model):
    CATEGORY_CHOICES = [
        ("threading", "Threading Tips"),
        ("henna", "Henna Care"),
        ("lashes", "Lash Maintenance"),
        ("beauty", "General Beauty"),
        ("news", "Salon News"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=250, unique=True)
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="blog_posts"
    )
    content = models.TextField()
    excerpt = models.TextField(max_length=500, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    featured_image = models.ImageField(upload_to="blog/%Y/%m/", blank=True, null=True)
    meta_description = models.CharField(max_length=160, blank=True)
    keywords = models.CharField(max_length=200, blank=True)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        # Auto-generate excerpt if not provided
        if not self.excerpt and self.content:
            self.excerpt = (
                self.content[:497] + "..." if len(self.content) > 500 else self.content
            )

        # Set published_at when first published
        if self.is_published and not self.published_at:
            from django.utils import timezone

            self.published_at = timezone.now()

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog:post-detail", kwargs={"slug": self.slug})
