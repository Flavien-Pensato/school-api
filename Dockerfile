FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

# WeasyPrint runtime libraries (pango, cairo, gdk-pixbuf) + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi8 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# collectstatic needs settings to load; real values come from the runtime env
RUN SECRET_KEY=build-only DEBUG=False \
    KEYCLOAK_SERVER_URL=https://build.invalid KEYCLOAK_REALM=build \
    KEYCLOAK_CLIENT_ID=build KEYCLOAK_CLIENT_SECRET=build \
    python manage.py collectstatic --noinput

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
