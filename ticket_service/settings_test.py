"""
Django settings for testing - uses SQLite in memory instead of PostgreSQL.
Imports all settings from the main settings and overrides database config.
"""

from ticket_service.settings import *  # noqa: F401, F403

# Override database for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
