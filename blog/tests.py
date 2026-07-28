from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import BlogPost

User = get_user_model()


class BlogAdminTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email="blog-admin@example.com",
            password="strong-test-password",
            first_name="Blog",
            last_name="Admin",
            phone_number="+14105550130",
            is_staff=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.staff)

    def test_create_uses_authenticated_admin_as_author(self):
        response = self.client.post(
            "/api/blog/",
            {
                "title": "Safe dashboard publishing",
                "content": "A useful article with enough content.",
                "category": "news",
                "is_published": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        post = BlogPost.objects.get()
        self.assertEqual(post.author, self.staff)

    def test_admin_list_includes_draft_status(self):
        BlogPost.objects.create(
            title="Draft article",
            slug="draft-article",
            author=self.staff,
            content="Draft content",
            category="news",
            is_published=False,
        )

        response = self.client.get("/api/blog/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("is_published", response.data["results"][0])
        self.assertFalse(response.data["results"][0]["is_published"])

    def test_duplicate_titles_receive_unique_slugs(self):
        payload = {
            "title": "Repeated title",
            "content": "Article content",
            "category": "news",
        }

        first = self.client.post("/api/blog/", payload, format="json")
        second = self.client.post("/api/blog/", payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.data["slug"], second.data["slug"])
