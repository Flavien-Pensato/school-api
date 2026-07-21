import jwt
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions

from core.keycloak import decode_access_token, extract_realm_roles, sync_user_roles


class KeycloakJWTAuthentication(authentication.BaseAuthentication):
    """Authenticate DRF requests with a Keycloak JWT access token.

    The Django user is keyed on preferred_username — the same value allauth
    uses for username — so API-created and admin-created users converge on
    the same row. Profile fields and role flags are re-synced on every
    authenticated request.
    """

    keyword = 'Bearer'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed('Invalid Authorization header.')

        try:
            claims = decode_access_token(header[1].decode())
        except jwt.PyJWTError as exc:
            raise exceptions.AuthenticationFailed(f'Invalid token: {exc}')

        user = self._get_or_create_user(claims)
        return (user, claims)

    def _get_or_create_user(self, claims):
        User = get_user_model()
        username = claims.get('preferred_username') or claims['sub']
        user, _created = User.objects.get_or_create(
            username=username,
            defaults={'email': claims.get('email', '')},
        )
        update_fields = []
        for field, claim in (
            ('email', 'email'),
            ('first_name', 'given_name'),
            ('last_name', 'family_name'),
        ):
            value = claims.get(claim, '')
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                update_fields.append(field)
        if sync_user_roles(user, extract_realm_roles(claims)):
            update_fields += ['is_staff', 'is_superuser']
        if update_fields:
            user.save(update_fields=update_fields)
        if not user.is_active:
            raise exceptions.AuthenticationFailed('User inactive.')
        return user

    def authenticate_header(self, request):
        # Returning a challenge makes DRF answer 401 instead of 403.
        return f'{self.keyword} realm="api"'
