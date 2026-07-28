from djoser.serializers import (
    UserCreatePasswordRetypeSerializer,
    UserSerializer as BaseUserSerializer,
)
from .models import User


class UserCreateSerializer(UserCreatePasswordRetypeSerializer):
    class Meta(UserCreatePasswordRetypeSerializer.Meta):
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "password",
        ]


class UserSerializer(BaseUserSerializer):
    class Meta(BaseUserSerializer.Meta):
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "phone_number",
            "email",
            "is_staff",
        ]
        read_only_fields = ["id", "is_staff"]
