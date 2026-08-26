from rest_framework.permissions import IsAuthenticated


def is_school_member(user):
    """Users allowed to see school data: superusers, or members of at least
    one school. Single source of truth for the API permission and for the
    admin mixin (`core.admin.SchoolScopedAdmin`)."""
    return user.is_superuser or user.school_memberships.exists()


class IsSchoolMember(IsAuthenticated):
    """Requires authentication plus membership in at least one school
    (superusers exempt). Real data isolation happens in the scoped
    querysets (`for_user`) and scoped serializer fields."""

    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and is_school_member(request.user)
        )
