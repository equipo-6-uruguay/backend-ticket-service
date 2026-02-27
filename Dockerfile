# Build stage
FROM python:3.12-slim AS builder


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


WORKDIR /app


RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .


RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# Runtime stage
FROM python:3.12-slim


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


RUN addgroup --system app && adduser --system --group app


WORKDIR /app


COPY --from=builder /install /usr/local


COPY --chown=app:app . .


USER app


EXPOSE 8000


CMD ["gunicorn", "ticket_service.wsgi:application", "--bind", "0.0.0.0:8000"]

