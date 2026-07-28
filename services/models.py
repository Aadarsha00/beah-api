from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Service(models.Model):
    SERVICE_CATEGORIES = [
        ("threading", "Threading"),
        ("henna", "Henna Art"),
        ("lashes", "Lashes"),
        ("combo", "Combo"),
        ("party", "Party Packages"),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    category = models.CharField(max_length=20, choices=SERVICE_CATEGORIES)
    duration_minutes = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} - ${self.price}"
