ARG PI_VERSION=0.80.9

FROM node:22-bookworm-slim AS pi
ARG PI_VERSION
RUN npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && node --version \
    && npm --version \
    && pi --version

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 workflow
COPY --from=pi /usr/local /usr/local
WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY alembic.ini ./
RUN pip install --no-cache-dir . \
    && mkdir -p /var/workflowengine \
    && chmod +x /app/backend/entrypoint.sh \
    && chown -R workflow:workflow /app /var/workflowengine
USER workflow
EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
