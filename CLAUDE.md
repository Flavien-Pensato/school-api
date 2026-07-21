# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run through uv (Python 3.13):

```bash
uv sync                                                        # install dependencies
uv run python manage.py runserver                              # dev server
uv run python manage.py test                                   # run all tests
uv run python manage.py test core.tests.test_rotation.ClassName.test_method  # single test
uv run python manage.py check && uv run python manage.py migrate  # system check + migrate
uv run python manage.py makemigrations                         # create migrations
```

On macOS, prefix test/server commands with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` so WeasyPrint finds pango (`brew install pango`); without it the PDF test auto-skips.

No linter, formatter, or type checker is configured.

## Code Principles

- **Django best practices**: prefer Django/DRF built-ins over custom code, fat models / thin views, keep code scoped to its app, always commit migrations.
- **DRY & KISS**: reuse Django/DRF machinery (generic views, serializers, managers) instead of reimplementing; no premature abstraction.
- **Clean architecture**: views handle HTTP concerns only; business logic lives in models (or service functions when it spans models); apps stay decoupled from each other.

## Architecture

Django 6 + Django REST Framework API.

- `config/` — project package. Single `settings.py` (no dev/prod split). Configuration comes from `.env` via django-environ (`SECRET_KEY`, `DEBUG` — defaults to False, `ALLOWED_HOSTS`, optional `DATABASE_URL`); copy `.env.example` to `.env` for local setup. Database defaults to SQLite; set `DATABASE_URL` for Postgres.
- `config/urls.py` mounts `admin/` (Keycloak SSO via allauth) and `api/` → `core.urls`. All API routes live under `/api/`.
- `core/` — the sole Django app. Layout: `models.py` (fat models + per-school scoped managers), `serializers.py`, `views.py` (ViewSets), `services.py` (logic spanning models: rotation, import, dashboards), `pdf.py`, `permissions.py`, `authentication.py`/`keycloak.py`/`adapters.py` (Keycloak JWT + SSO), `tests/` package.
- DRF defaults (`config/settings.py`): `PageNumberPagination` (`PAGE_SIZE = 20`), auth = Keycloak JWT + session, permission = `IsAuthenticated`. Every view still declares `permission_classes` explicitly — domain views use `core.permissions.IsSchoolMember`.

## Domain rules

- **"Year" always means the French school year** (*année scolaire*): ~September → June, spans two calendar years, named "2026-2027". Never assume calendar-year alignment; `Week` rows (one per ISO Monday in the `SchoolYear` range) are the anchor for presence/assignments — not raw ISO week numbers.
- Multi-school: every queryset must go through `.for_user(user)` (scoped managers) and writable FKs through `UserScopedPKField` — data is isolated per `SchoolMembership`.
- `Enrollment` = student ↔ class ↔ group for one year; students persist across years.
- Rotation (`services.generate_week_assignments`): each active task → one group among present classes' groups; rest + pair fairness from same-year history; `is_manual=True` assignments survive regeneration.
