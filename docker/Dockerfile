FROM ghcr.io/astral-sh/uv:latest AS builder

RUN apk add --no-cache gcc postgresql-dev musl-dev

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen

FROM python:3.12-alpine AS runtime

RUN apk add --no-cache libpq postgresql-client wget curl bc

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY . .

RUN addgroup -S app && adduser -S app -G app && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "docker-entrypoint.sh"]
