from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q

from .models import Promotion, ContactMessage, AdminNote
from .serializers import (
    PromotionSerializer,
    PromotionCreateUpdateSerializer,
    ContactMessageSerializer,
    ContactMessageCreateSerializer,
    ContactMessageUpdateSerializer,
    AdminNoteSerializer,
    AdminNoteCreateUpdateSerializer,
)


class PromotionViewSet(viewsets.ModelViewSet):
    queryset = Promotion.objects.all()
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active", "start_date", "end_date"]
    search_fields = ["title", "description"]
    ordering_fields = ["start_date", "end_date", "created_at"]
    ordering = ["-start_date"]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return PromotionCreateUpdateSerializer
        return PromotionSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    @action(detail=False, methods=["get"])
    def active(self, request):
        """Get currently active promotions"""
        today = timezone.now().date()
        active_promotions = self.queryset.filter(
            is_active=True, start_date__lte=today, end_date__gte=today
        )
        serializer = self.get_serializer(active_promotions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        """Get upcoming promotions"""
        today = timezone.now().date()
        upcoming_promotions = self.queryset.filter(is_active=True, start_date__gt=today)
        serializer = self.get_serializer(upcoming_promotions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def expired(self, request):
        """Get expired promotions"""
        today = timezone.now().date()
        expired_promotions = self.queryset.filter(end_date__lt=today)
        serializer = self.get_serializer(expired_promotions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):
        """Toggle promotion active status"""
        promotion = self.get_object()
        promotion.is_active = not promotion.is_active
        promotion.save()
        serializer = self.get_serializer(promotion)
        return Response(serializer.data)


class ContactMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactMessage.objects.all()
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_read", "is_responded"]
    search_fields = ["name", "email", "subject", "message"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return ContactMessageCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return ContactMessageUpdateSerializer
        return ContactMessageSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated(), permissions.IsAdminUser()]

    def create(self, request, *args, **kwargs):
        """Allow anyone to create a contact message"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {"message": "Your message has been sent successfully!"},
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    @action(detail=False, methods=["get"])
    def unread(self, request):
        """Get unread messages"""
        unread_messages = self.queryset.filter(is_read=False)
        serializer = self.get_serializer(unread_messages, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def pending(self, request):
        """Get messages that are read but not responded"""
        pending_messages = self.queryset.filter(is_read=True, is_responded=False)
        serializer = self.get_serializer(pending_messages, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark message as read"""
        message = self.get_object()
        message.is_read = True
        message.save()
        serializer = self.get_serializer(message)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def mark_responded(self, request, pk=None):
        """Mark message as responded"""
        message = self.get_object()
        message.is_responded = True
        if not message.is_read:
            message.is_read = True
        message.save()
        serializer = self.get_serializer(message)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Get contact messages statistics"""
        total = self.queryset.count()
        unread = self.queryset.filter(is_read=False).count()
        pending = self.queryset.filter(is_read=True, is_responded=False).count()
        responded = self.queryset.filter(is_responded=True).count()

        return Response(
            {
                "total": total,
                "unread": unread,
                "pending": pending,
                "responded": responded,
            }
        )


class AdminNoteViewSet(viewsets.ModelViewSet):
    queryset = AdminNote.objects.all()
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_important", "created_by"]
    search_fields = ["title", "content"]
    ordering_fields = ["created_at", "updated_at", "is_important"]
    ordering = ["-is_important", "-created_at"]
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return AdminNoteCreateUpdateSerializer
        return AdminNoteSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"])
    def important(self, request):
        """Get important notes"""
        important_notes = self.queryset.filter(is_important=True)
        serializer = self.get_serializer(important_notes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_notes(self, request):
        """Get notes created by current user"""
        my_notes = self.queryset.filter(created_by=request.user)
        serializer = self.get_serializer(my_notes, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def toggle_important(self, request, pk=None):
        """Toggle note importance"""
        note = self.get_object()
        note.is_important = not note.is_important
        note.save()
        serializer = self.get_serializer(note)
        return Response(serializer.data)
