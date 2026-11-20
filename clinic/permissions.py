from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Anyone can read (GET); only administrators (is_staff) can change data."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsAdmin(permissions.BasePermission):
    """Only administrators."""
    message = 'Administrator access required.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsOwnerOrAdmin(permissions.BasePermission):
    """Patients can only touch their own appointments; admins can touch all."""
    message = 'You can only manage your own appointments.'

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return obj.patient == request.user
