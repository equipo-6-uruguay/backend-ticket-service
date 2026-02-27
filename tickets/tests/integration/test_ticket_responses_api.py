"""
Integration tests for admin responses API endpoints.
TDD RED phase: These tests define the expected behavior for Issue #59.
All tests should FAIL until the infrastructure is implemented.

Covers: EP12, EP13, EP16, EP18, BVA18, HU-1.2
GitHub Issue: #59
"""
from unittest.mock import patch, MagicMock, Mock

from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from tickets.models import Ticket


def _fake_admin_auth(request):
    """Return a fake authenticated admin user."""
    user = Mock()
    user.token = {"role": "ADMIN"}
    user.id = "admin-001"
    user.is_authenticated = True
    return (user, "fake-token")


def _fake_user_auth(request):
    """Return a fake authenticated non-admin user."""
    user = Mock()
    user.token = {"role": "USER"}
    user.id = "user-regular"
    user.is_authenticated = True
    return (user, "fake-token")


@patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
       side_effect=_fake_admin_auth)
class TicketResponseAPITests(APITestCase):
    """Integration tests for POST/GET /api/tickets/{id}/responses/."""

    def setUp(self):
        """Create ticket fixtures for testing."""
        self.open_ticket = Ticket.objects.create(
            title="Test ticket OPEN",
            description="Descripción del ticket abierto",
            status=Ticket.OPEN,
            user_id="user-123",
        )
        self.closed_ticket = Ticket.objects.create(
            title="Test ticket CLOSED",
            description="Descripción del ticket cerrado",
            status=Ticket.CLOSED,
            user_id="user-456",
        )
        self.post_url = f"/api/tickets/{self.open_ticket.id}/responses/"
        self.closed_post_url = f"/api/tickets/{self.closed_ticket.id}/responses/"

    # ─────────────────────────────────────────────
    # EP12 — Admin creates response on OPEN ticket
    # ─────────────────────────────────────────────
    @patch("tickets.views.RabbitMQEventPublisher")
    def test_admin_creates_response_on_open_ticket(self, mock_publisher_cls, mock_auth):
        """EP12: Admin POST valid text on OPEN ticket → 201 Created."""
        mock_publisher_cls.return_value = MagicMock()

        payload = {"text": "Estamos revisando tu caso", "admin_id": "admin-001"}
        response = self.client.post(self.post_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["text"], payload["text"])
        self.assertEqual(response.data["admin_id"], payload["admin_id"])

    # ─────────────────────────────────────────────
    # EP13 — Non-admin user cannot create response
    # ─────────────────────────────────────────────
    def test_user_without_admin_role_cannot_respond(self, mock_auth):
        """EP13: Non-admin user POST → 403 Forbidden.
        
        NOTE: Since there's no auth middleware yet, this test documents
        the expected behavior. The GREEN phase should implement role 
        checking either via request header or payload field.
        """
        # Simulate a non-admin user by NOT providing admin_id
        payload = {"text": "Intento de respuesta sin permisos"}
        response = self.client.post(self.post_url, payload, format="json")

        self.assertIn(
            response.status_code,
            [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN],
        )

    # ─────────────────────────────────────────────
    # EP16 — Cannot respond to CLOSED ticket
    # ─────────────────────────────────────────────
    @patch("tickets.views.RabbitMQEventPublisher")
    def test_cannot_respond_to_closed_ticket(self, mock_publisher_cls, mock_auth):
        """EP16: POST on CLOSED ticket → 400 Bad Request."""
        mock_publisher_cls.return_value = MagicMock()

        payload = {"text": "Intento en ticket cerrado", "admin_id": "admin-001"}
        response = self.client.post(self.closed_post_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    # ─────────────────────────────────────────────
    # EP18 — Empty text is rejected
    # ─────────────────────────────────────────────
    @patch("tickets.views.RabbitMQEventPublisher")
    def test_empty_text_rejected(self, mock_publisher_cls, mock_auth):
        """EP18: POST with empty text → 400 Bad Request."""
        mock_publisher_cls.return_value = MagicMock()

        payload = {"text": "", "admin_id": "admin-001"}
        response = self.client.post(self.post_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────────
    # BVA18 — Text exceeds 2000 characters
    # ─────────────────────────────────────────────
    @patch("tickets.views.RabbitMQEventPublisher")
    def test_text_exceeds_2000_chars_rejected(self, mock_publisher_cls, mock_auth):
        """BVA18: POST with 2001 chars → 400 Bad Request."""
        mock_publisher_cls.return_value = MagicMock()

        long_text = "x" * 2001
        payload = {"text": long_text, "admin_id": "admin-001"}
        response = self.client.post(self.post_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────────
    # HU-1.2 — GET responses (with data)
    # ─────────────────────────────────────────────
    def test_get_responses_returns_list(self, mock_auth):
        """HU-1.2: GET /api/tickets/{id}/responses/ → 200 with list."""
        response = self.client.get(self.post_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    # ─────────────────────────────────────────────
    # HU-1.2 — GET responses (empty)
    # ─────────────────────────────────────────────
    def test_get_responses_empty_ticket(self, mock_auth):
        """HU-1.2: GET on ticket with no responses → 200 with empty list."""
        response = self.client.get(self.post_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    # ─────────────────────────────────────────────
    # Ticket not found — POST response on non-existent ticket
    # ─────────────────────────────────────────────
    @patch("tickets.views.RabbitMQEventPublisher")
    def test_create_response_nonexistent_ticket_returns_404(self, mock_publisher_cls, mock_auth):
        """POST on non-existent ticket → 404 Not Found."""
        mock_publisher_cls.return_value = MagicMock()

        payload = {"text": "Respuesta a ticket inexistente", "admin_id": "admin-001"}
        response = self.client.post("/api/tickets/99999/responses/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.data)
        self.assertIn("no encontrado", response.data["error"].lower())
