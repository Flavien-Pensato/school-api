from rest_framework.permissions import IsAuthenticated


class IsSchoolMember(IsAuthenticated):
    """Requires authentication plus membership in at least one school
    (superusers exempt). Real data isolation happens in the scoped
    querysets (`for_user`) and scoped serializer fields."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        return user.is_superuser or user.school_memberships.exists()
