# school-api

Django REST API for weekly task (chore) assignment in MFR-style schools:
classes alternate on-site weeks, and tasks rotate fairly across student
groups.

## Setup

```bash
uv sync
cp .env.example .env      # fill in SECRET_KEY + Keycloak settings
uv run python manage.py migrate
uv run python manage.py runserver
```

### PDF export (WeasyPrint)

The printable week dashboard (`GET /api/weeks/{id}/dashboard/pdf/`) uses
WeasyPrint, which needs the pango system library:

- **macOS**: `brew install pango`, then run the server and tests with
  `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (dyld does not search
  Homebrew's lib directory by default).
- **Debian/Ubuntu/Docker**: `apt install libpango-1.0-0 libpangoft2-1.0-0`.

Everything else works without pango; the PDF test auto-skips when the
library is missing.

## Tests

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run python manage.py test
```

## Domain

- **School** → **SchoolYear** (French *année scolaire*, e.g. "2026-2027",
  September → June) → **Week** (one per ISO Monday in the year range).
- **Student** persists across years; **Enrollment** ties them to a
  **SchoolClass** (per-year) and optional **Group** — one per year.
- **ClassPresence** marks which classes are on-site each week.
- **Assignment** links one **Task** to one Group per week
  (`POST /api/weeks/{id}/generate-assignments/` runs the fair rotation;
  staff edits through `/api/assignments/` become manual overrides that
  survive regeneration).
- Staff access is scoped per school via **SchoolMembership** (managed in
  Django admin).

Key endpoints: `/api/students/import/` (CSV/XLSX upload),
`/api/weeks/{id}/dashboard/` (+ `/pdf/`), `/api/school-years/{id}/stats/`
(group×task fairness matrix).
