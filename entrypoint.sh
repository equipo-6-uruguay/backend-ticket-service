#!/bin/sh

set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Starting Gunicorn server..."
exec gunicorn ticket_service.wsgi:application --bind 0.0.0.0:8000
