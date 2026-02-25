"""
Shared pytest fixtures for E2E tests.

Provides authenticated API clients, mock boundaries for auth and event
publishing, and helper functions to create tickets through the API.
All E2E tests in this directory consume these fixtures.
"""

import pytest
from unittest.mock import Mock, patch

from rest_framework.test import APIClient


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    """Return a plain DRF APIClient instance."""
    return APIClient()


# ---------------------------------------------------------------------------
# Auth mocking helpers (internal)
# ---------------------------------------------------------------------------

def _build_mock_user(user_id, role):
    """Build a mock user object that mimics the JWT stateless user."""
    mock_user = Mock()
    mock_user.id = user_id
    mock_user.token = {"role": role}
    mock_user.is_authenticated = True
    return mock_user


# ---------------------------------------------------------------------------
# Admin auth fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth_admin():
    """Patch CookieJWTStatelessAuthentication to return an ADMIN user.

    Yields the mock so tests can inspect call counts if needed.
    """
    mock_user = _build_mock_user(user_id="admin-1", role="ADMIN")
    with patch(
        "tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
        return_value=(mock_user, "fake-token"),
    ) as mock_auth:
        yield mock_auth


# ---------------------------------------------------------------------------
# Regular user auth fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth_user():
    """Patch CookieJWTStatelessAuthentication to return a regular USER.

    Yields the mock so tests can inspect call counts if needed.
    """
    mock_user = _build_mock_user(user_id="user-1", role="USER")
    with patch(
        "tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
        return_value=(mock_user, "fake-token"),
    ) as mock_auth:
        yield mock_auth


# ---------------------------------------------------------------------------
# Event publisher mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_event_publisher():
    """Patch RabbitMQEventPublisher.publish to a no-op Mock.

    Yields the mock so tests can assert on published events.
    """
    with patch(
        "tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish"
    ) as mock_publish:
        yield mock_publish


# ---------------------------------------------------------------------------
# Ticket creation helper
# ---------------------------------------------------------------------------

@pytest.fixture
def create_ticket(api_client):
    """Return a helper function that creates a ticket via the API.

    The helper POSTs to ``/api/tickets/`` with sensible defaults and
    returns the parsed JSON response body.  Callers may override any
    field through keyword arguments.

    Usage::

        data = create_ticket()
        data = create_ticket(title="Custom title", user_id="user-42")
    """

    def _create(**overrides):
        defaults = {
            "title": "E2E Test Ticket",
            "description": "Ticket created during E2E test run",
            "user_id": "user-1",
        }
        defaults.update(overrides)
        response = api_client.post("/api/tickets/", defaults, format="json")
        assert response.status_code == 201, (
            f"Expected 201 on ticket creation, got {response.status_code}: "
            f"{response.data}"
        )
        return response.data

    return _create
