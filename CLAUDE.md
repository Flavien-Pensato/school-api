# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run through uv (Python 3.13):

```bash
uv sync                                                        # install dependencies
uv run python manage.py runserver                              # dev server
uv run python manage.py test                                   # run all tests
uv run python manage.py test core.tests.ClassName.test_method  # run a single test
uv run python manage.py check && uv run python manage.py migrate  # system check + migrate
uv run python manage.py makemigrations                         # create migrations
```

No linter, formatter, or type checker is configured.

## Code Principles

- **Django best practices**: prefer Django/DRF built-ins over custom code, fat models / thin views, keep code scoped to its app, always commit migrations.
- **DRY & KISS**: reuse Django/DRF machinery (generic views, serializers, managers) instead of reimplementing; no premature abstraction.
- **Clean architecture**: views handle HTTP concerns only; business logic lives in models (or service functions when it spans models); apps stay decoupled from each other.

## Architecture

Django 6 + Django REST Framework API.

- `config/` — project package. Single `settings.py` (no dev/prod split). Configuration comes from `.env` via django-environ (`SECRET_KEY`, `DEBUG` — defaults to False, `ALLOWED_HOSTS`, optional `DATABASE_URL`); copy `.env.example` to `.env` for local setup. Database defaults to SQLite; set `DATABASE_URL` for Postgres.
- `config/urls.py` mounts `admin/` and `api/` → `core.urls`. All API routes live under `/api/`.
- `core/` — the sole Django app. DRF class-based views (e.g. `HealthCheckView` at `/api/health/`).
- DRF is configured with `PageNumberPagination` (`PAGE_SIZE = 20`). Default authentication/permission classes are intentionally unset (open TODO in `config/settings.py`) — every new view must declare `permission_classes` explicitly.
