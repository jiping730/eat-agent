FROM node:22-bookworm-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY . .
COPY --from=frontend-build /frontend/dist /app/frontend/dist
RUN pip install .

RUN addgroup --system --gid 10001 appgroup \
    && adduser --system --uid 10001 --ingroup appgroup appuser \
    && mkdir -p /app/data /tmp \
    && chown -R appuser:appgroup /app /tmp

USER appuser

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "-k", "uvicorn.workers.UvicornWorker", "front.app:app"]
