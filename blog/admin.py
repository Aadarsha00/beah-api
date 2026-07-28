from django.contrib import admin
from .models import BlogPost


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "category",
        "is_published",
        "is_featured",
        "views_count",
        "published_at",
    )
    list_filter = ("category", "is_published", "is_featured", "published_at")
    search_fields = ("title", "content", "keywords")
    list_editable = ("is_published", "is_featured")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("-published_at", "-created_at")
    readonly_fields = ("views_count", "created_at", "updated_at", "published_at")

    fieldsets = (
        (
            "Post Details",
            {"fields": ("title", "slug", "author", "category", "featured_image")},
        ),
        ("Content", {"fields": ("content", "excerpt")}),
        ("SEO", {"fields": ("meta_description", "keywords"), "classes": ("collapse",)}),
        ("Status", {"fields": ("is_published", "is_featured")}),
        (
            "Statistics",
            {
                "fields": ("views_count", "created_at", "updated_at", "published_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)
