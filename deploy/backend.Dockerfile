# syntax=docker/dockerfile:1.4

ARG PYTHON_VERSION=3.11-slim

FROM python:${PYTHON_VERSION} AS builder

WORKDIR /opt/app

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install --prefix /install --no-cache-dir -r requirements.txt

COPY backend/ /opt/app/

FROM python:${PYTHON_VERSION} AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY --from=builder /install /usr/local
COPY backend/ /srv/app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

