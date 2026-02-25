"""
Integration tests for generic 500 error handling on custom endpoints.

Verifies that unexpected infrastructure failures (DB errors, RabbitMQ timeouts,
etc.) return a safe, generic HTTP 500 response with body:
    {"error": "Error interno del servidor"}

Also includes negative regression tests to confirm that known domain exceptions
(ValueError, TicketAlreadyClosed, InvalidPriorityTransition, DomainException)
still produce their expected 400/403 codes and are NOT swallowed by the
generic catch-all.

GitHub Issue: #8
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import Mock, patch

from tickets.models import Ticket as DjangoTicket


class TestGeneric500ChangeStatus(TestCase):
    """Integration tests for generic 500 handling on PATCH /api/tickets/{id}/status/."""

    def setUp(self):
        self.client = APIClient()
        self.ticket = DjangoTicket.objects.create(
            title="Status 500 Test",
            description="Integration test ticket",
            status="OPEN",
            user_id="user-1",
        )
        self.url = f"/api/tickets/{self.ticket.id}/status/"

        # Mock authentication so the request is not rejected by JWT
        self.auth_patcher = patch(
            "tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate"
        )
        self.mock_auth = self.auth_patcher.start()
        mock_user = Mock()
        mock_user.token = {"role": "ADMIN"}
        mock_user.id = "admin-1"
        mock_user.is_authenticated = True
        self.mock_auth.return_value = (mock_user, "fake-token")

        # Mock RabbitMQ to avoid real connection
        self.publisher_patcher = patch(
            "tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish"
        )
        self.mock_publish = self.publisher_patcher.start()

    def tearDown(self):
        self.auth_patcher.stop()
        self.publisher_patcher.stop()
        DjangoTicket.objects.all().delete()

    def test_change_status_infra_failure_returns_500(self):
        """Infra failure (repository save) during change_status returns generic 500."""
        with patch(
            "tickets.infrastructure.repository.DjangoTicketRepository.save",
            side_effect=RuntimeError("DB connection lost"),
        ):
            response = self.client.patch(
                self.url, {"status": "IN_PROGRESS"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"error": "Error interno del servidor"})

    def test_change_status_event_publisher_failure_returns_500(self):
        """Event publisher failure during change_status returns generic 500."""
        self.mock_publish.side_effect = RuntimeError("RabbitMQ unreachable")

        response = self.client.patch(
            self.url, {"status": "IN_PROGRESS"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"error": "Error interno del servidor"})

    def test_change_status_value_error_still_returns_400(self):
        """Regression: ValueError in change_status still returns 400, not 500."""
        response = self.client.patch(
            self.url, {"status": "INVALID_STATE"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_status_missing_field_still_returns_400(self):
        """Regression: Missing 'status' field still returns 400, not 500."""
        response = self.client.patch(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_status_ticket_already_closed_still_returns_400(self):
        """Regression: TicketAlreadyClosed still returns 400, not 500."""
        # Move ticket to CLOSED via the proper state machine
        self.ticket.status = "IN_PROGRESS"
        self.ticket.save()
        self.client.patch(self.url, {"status": "CLOSED"}, format="json")
        self.mock_publish.reset_mock()

        response = self.client.patch(
            self.url, {"status": "OPEN"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestGeneric500ChangePriority(TestCase):
    """Integration tests for generic 500 handling on PATCH /api/tickets/{id}/priority/."""

    def setUp(self):
        self.client = APIClient()
        self.ticket = DjangoTicket.objects.create(
            title="Priority 500 Test",
            description="Integration test ticket",
            status="OPEN",
            user_id="user-1",
        )
        self.url = f"/api/tickets/{self.ticket.id}/priority/"

        # Mock authentication — admin user
        self.auth_patcher = patch(
            "tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate"
        )
        self.mock_auth = self.auth_patcher.start()
        mock_user = Mock()
        mock_user.token = {"role": "ADMIN"}
        mock_user.id = "admin-1"
        mock_user.is_authenticated = True
        self.mock_auth.return_value = (mock_user, "fake-token")

        # Mock RabbitMQ
        self.publisher_patcher = patch(
            "tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish"
        )
        self.mock_publish = self.publisher_patcher.start()

    def tearDown(self):
        self.auth_patcher.stop()
        self.publisher_patcher.stop()
        DjangoTicket.objects.all().delete()

    def test_change_priority_infra_failure_returns_500(self):
        """Infra failure (repository save) during change_priority returns generic 500."""
        with patch(
            "tickets.infrastructure.repository.DjangoTicketRepository.save",
            side_effect=RuntimeError("DB connection lost"),
        ):
            response = self.client.patch(
                self.url, {"priority": "High"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"error": "Error interno del servidor"})

    def test_change_priority_event_publisher_failure_returns_500(self):
        """Event publisher failure during change_priority returns generic 500."""
        self.mock_publish.side_effect = RuntimeError("RabbitMQ timeout")

        response = self.client.patch(
            self.url, {"priority": "High"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"error": "Error interno del servidor"})

    def test_change_priority_invalid_transition_still_returns_400(self):
        """Regression: InvalidPriorityTransition still returns 400, not 500."""
        # First set priority to High
        self.client.patch(self.url, {"priority": "High"}, format="json")

        # Attempt invalid transition back to Unassigned
        response = self.client.patch(
            self.url, {"priority": "Unassigned"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_priority_permission_denied_still_returns_403(self):
        """Regression: DomainException (permission denied) still returns 403, not 500."""
        # Switch to non-admin user
        mock_user = Mock()
        mock_user.token = {"role": "USER"}
        mock_user.id = "user-1"
        mock_user.is_authenticated = True
        self.mock_auth.return_value = (mock_user, "fake-token")

        response = self.client.patch(
            self.url, {"priority": "High"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_change_priority_missing_field_still_returns_400(self):
        """Regression: Missing 'priority' field still returns 400, not 500."""
        response = self.client.patch(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestGeneric500MyTickets(TestCase):
    """Integration tests for generic 500 handling on GET /api/tickets/my-tickets/{user_id}/."""

    def setUp(self):
        self.client = APIClient()
        self.user_id = "user-500-test"
        self.url = f"/api/tickets/my-tickets/{self.user_id}/"

        # Mock authentication
        self.auth_patcher = patch(
            "tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate"
        )
        self.mock_auth = self.auth_patcher.start()
        mock_user = Mock()
        mock_user.token = {"role": "USER"}
        mock_user.id = self.user_id
        mock_user.is_authenticated = True
        self.mock_auth.return_value = (mock_user, "fake-token")

        # Mock RabbitMQ
        self.publisher_patcher = patch(
            "tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish"
        )
        self.mock_publish = self.publisher_patcher.start()

    def tearDown(self):
        self.auth_patcher.stop()
        self.publisher_patcher.stop()
        DjangoTicket.objects.all().delete()

    def test_my_tickets_infra_failure_returns_500(self):
        """Infra failure (ORM query) during my_tickets returns generic 500."""
        with patch(
            "tickets.views.Ticket.objects.filter",
            side_effect=RuntimeError("DB OperationalError simulated"),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"error": "Error interno del servidor"})

    def test_my_tickets_does_not_leak_exception_details(self):
        """Generic 500 response must not contain internal exception message."""
        with patch(
            "tickets.views.Ticket.objects.filter",
            side_effect=RuntimeError("secret internal details"),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertNotIn("secret", str(response.data))
        self.assertNotIn("Error al obtener tickets", str(response.data))

    def test_my_tickets_normal_operation_returns_200(self):
        """Regression: Normal operation still returns 200 with ticket list."""
        DjangoTicket.objects.create(
            title="My Ticket",
            description="Test",
            status="OPEN",
            user_id=self.user_id,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "My Ticket")
