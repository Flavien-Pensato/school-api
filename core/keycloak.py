"""Shared Keycloak token verification and role mapping.

Used by both the allauth adapter (browser/admin login) and the DRF
authentication class (API bearer tokens).
"""

from functools import lru_cache

import jwt
from django.conf import settings

# Keycloak realm roles mapped to Django flags.
STAFF_ROLE = 'django-staff'
SUPERUSER_ROLE = 'django-superuser'


@lru_cache(maxsize=1)
def get_jwks_client() -> jwt.PyJWKClient:
    # PyJWKClient caches keys and refetches on unknown kid, which covers
    # Keycloak signing-key rotation.
    return jwt.PyJWKClient(settings.KEYCLOAK_JWKS_URL, cache_keys=True)


def decode_access_token(raw_token: str) -> dict:
    """Verify signature, issuer and expiry of a Keycloak access token.

    Keycloak access tokens carry aud='account' unless an audience mapper is
    configured, so instead of verifying aud we require azp (authorized party)
    to be our client.
    """
    signing_key = get_jwks_client().get_signing_key_from_jwt(raw_token)
    claims = jwt.decode(
        raw_token,
        signing_key.key,
        algorithms=['RS256'],
        issuer=settings.KEYCLOAK_ISSUER,
        options={'verify_aud': False},
    )
    if claims.get('azp') != settings.KEYCLOAK_CLIENT_ID:
        raise jwt.InvalidTokenError('Token was not issued for this client (azp mismatch)')
    return claims


def extract_realm_roles(claims: dict) -> set[str]:
    return set(claims.get('realm_access', {}).get('roles', []))


def sync_user_roles(user, roles: set[str]) -> bool:
    """Map Keycloak realm roles to Django flags. Returns True if user changed."""
    is_superuser = SUPERUSER_ROLE in roles
    is_staff = is_superuser or STAFF_ROLE in roles
    changed = user.is_staff != is_staff or user.is_superuser != is_superuser
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    return changed
