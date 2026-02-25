"""
Conftest raíz para pytest-django.
Usa ticket_service.settings_test para pruebas (SQLite en memoria).
"""
import os

os.environ.setdefault("TICKET_SERVICE_SECRET_KEY", "test-secret-key")