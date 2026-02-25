"""
E2E tests — Error and invalid-transition scenarios.

Scenario 3: Verify the API correctly rejects illegal operations and
returns appropriate HTTP error codes and messages.
"""

import pytest


@pytest.mark.django_db
class TestErrorFlows:
    """Validate domain rules surface as correct HTTP errors."""

    # -- helpers ----------------------------------------------------------

    def _close_ticket(self, api_client, ticket_id):
        """Move a ticket through OPEN → IN_PROGRESS → CLOSED."""
        resp = api_client.patch(
            f"/api/tickets/{ticket_id}/status/",
            {"status": "IN_PROGRESS"},
            format="json",
        )
        assert resp.status_code == 200

        resp = api_client.patch(
            f"/api/tickets/{ticket_id}/status/",
            {"status": "CLOSED"},
            format="json",
        )
        assert resp.status_code == 200
        return resp

    # -- closed ticket restrictions ---------------------------------------

    def test_closed_ticket_cannot_change_status(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """CLOSED → OPEN must be rejected with 400."""
        ticket = create_ticket()
        self._close_ticket(api_client, ticket["id"])

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/status/",
            {"status": "OPEN"},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    def test_closed_ticket_cannot_change_priority(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Changing priority on a CLOSED ticket must be rejected with 400."""
        ticket = create_ticket()
        self._close_ticket(api_client, ticket["id"])

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/priority/",
            {"priority": "High", "justification": "Urgente"},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    def test_closed_ticket_cannot_add_response(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Adding a response to a CLOSED ticket must be rejected with 400."""
        ticket = create_ticket()
        self._close_ticket(api_client, ticket["id"])

        resp = api_client.post(
            f"/api/tickets/{ticket['id']}/responses/",
            {"text": "Intento tardío", "admin_id": "admin-1"},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    # -- invalid state transitions ----------------------------------------

    def test_invalid_state_transition_open_to_closed(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """OPEN → CLOSED (skipping IN_PROGRESS) must be rejected with 400."""
        ticket = create_ticket()

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/status/",
            {"status": "CLOSED"},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    # -- resource not found -----------------------------------------------

    def test_nonexistent_ticket_returns_404(
        self, api_client, mock_auth_admin, mock_event_publisher
    ):
        """Status change on a non-existent ticket returns 404."""
        resp = api_client.patch(
            "/api/tickets/99999/status/",
            {"status": "IN_PROGRESS"},
            format="json",
        )
        assert resp.status_code == 404
        assert "error" in resp.data

    # -- missing required fields ------------------------------------------

    def test_missing_status_field_returns_400(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Empty payload to status endpoint returns 400."""
        ticket = create_ticket()

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/status/",
            {},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    # -- priority business rules ------------------------------------------

    def test_priority_revert_to_unassigned_returns_400(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Setting priority to Medium then reverting to Unassigned must fail."""
        ticket = create_ticket()

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/priority/",
            {"priority": "Medium", "justification": "Escalar"},
            format="json",
        )
        assert resp.status_code == 200

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/priority/",
            {"priority": "Unassigned"},
            format="json",
        )
        assert resp.status_code == 400
        assert "error" in resp.data

    # -- permission checks ------------------------------------------------

    def test_non_admin_cannot_change_priority(
        self, api_client, mock_auth_user, mock_event_publisher, create_ticket
    ):
        """A regular USER cannot change ticket priority (403)."""
        ticket = create_ticket()

        resp = api_client.patch(
            f"/api/tickets/{ticket['id']}/priority/",
            {"priority": "High", "justification": "Intento sin permisos"},
            format="json",
        )
        assert resp.status_code == 403
        assert "error" in resp.data
