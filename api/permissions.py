from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed for any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the object.
        return obj.created_by == request.user


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow admins to edit, others can only read.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_staff


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to allow access to owners or admin users.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        # Admin users have full access
        if request.user and request.user.is_staff:
            return True

        # Owners have full access to their own objects
        if hasattr(obj, "client"):
            return obj.client == request.user
        if hasattr(obj, "created_by"):
            return obj.created_by == request.user

        return False


class CanManagePromotions(permissions.BasePermission):
    """
    Custom permission for promotion management.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and (
            request.user.is_staff or request.user.has_perm("your_app.change_promotion")
        )


class CanViewContactMessages(permissions.BasePermission):
    """
    Custom permission for viewing contact messages.
    """

    def has_permission(self, request, view):
        # Anyone can create contact messages
        if request.method == "POST":
            return True

        # Only staff can view/manage contact messages
        return request.user and request.user.is_staff


class CanManageAdminNotes(permissions.BasePermission):
    """
    Custom permission for admin notes management.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        # Superusers can do anything
        if request.user.is_superuser:
            return True

        # Staff users can only edit their own notes unless they're viewing
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.created_by == request.user
