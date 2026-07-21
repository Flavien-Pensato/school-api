from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from core.keycloak import decode_access_token, extract_realm_roles, sync_user_roles


class KeycloakSocialAccountAdapter(DefaultSocialAccountAdapter):
    """SSO-only adapter: syncs Keycloak realm roles to Django flags on every login."""

    def pre_social_login(self, request, sociallogin):
        roles = self._get_roles(sociallogin)
        user = sociallogin.user
        changed = sync_user_roles(user, roles)
        if user.pk and changed:
            # Existing user: save_user() only runs on signup, persist here.
            user.save(update_fields=['is_staff', 'is_superuser'])
        # New user (no pk yet): flags are persisted by allauth's auto-signup.

    def _get_roles(self, sociallogin) -> set[str]:
        # Roles appear in userinfo/ID token (hence extra_data) only if a
        # Keycloak realm-roles mapper is configured; Keycloak puts them in the
        # access token by default, so fall back to decoding that.
        roles = extract_realm_roles(sociallogin.account.extra_data)
        if roles:
            return roles
        token = getattr(sociallogin, 'token', None)
        if token and token.token:
            try:
                return extract_realm_roles(decode_access_token(token.token))
            except Exception:
                return set()
        return set()
