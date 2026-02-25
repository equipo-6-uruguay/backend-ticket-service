"""
E2E tests — Ticket lifecycle and domain flow scenarios.

Scenario 1: Full ticket lifecycle (OPEN → IN_PROGRESS → CLOSED).
Scenario 2: Priority changes with admin responses.
"""

import pytest


@pytest.mark.django_db
class TestTicketFullLifecycle:
    """Scenario 1: Create a ticket, move through every valid state, verify."""

    def test_create_change_status_close_flow(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """OPEN → IN_PROGRESS → CLOSED full lifecycle through the API."""
        # --- Given: a new ticket is created ---
        ticket = create_ticket()
        ticket_id = ticket["id"]
        assert ticket["status"] == "OPEN"

        # --- When: status is changed to IN_PROGRESS ---
        resp = api_client.patch(
            f"/api/tickets/{ticket_id}/status/",
            {"status": "IN_PROGRESS"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "IN_PROGRESS"

        # --- When: status is changed to CLOSED ---
        resp = api_client.patch(
            f"/api/tickets/{ticket_id}/status/",
            {"status": "CLOSED"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "CLOSED"

        # --- Then: GET confirms the ticket is CLOSED ---
        resp = api_client.get(f"/api/tickets/{ticket_id}/")
        assert resp.status_code == 200
        assert resp.data["status"] == "CLOSED"

    def test_get_ticket_detail_after_creation(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Verify GET detail returns the newly created ticket."""
        ticket = create_ticket(title="Detail check")
        resp = api_client.get(f"/api/tickets/{ticket['id']}/")
        assert resp.status_code == 200
        assert resp.data["title"] == "Detail check"
        assert resp.data["status"] == "OPEN"

    def test_list_tickets_includes_created_ticket(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Verify GET list includes the ticket just created."""
        ticket = create_ticket(title="Listed ticket")
        resp = api_client.get("/api/tickets/")
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.data]
        assert ticket["id"] in ids


@pytest.mark.django_db
class TestPriorityAndResponseFlow:
    """Scenario 2: Priority changes and admin responses."""

    def test_create_change_priority_add_response_flow(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Create ticket → change priority → add response → verify."""
        # --- Given: a new ticket ---
        ticket = create_ticket()
        ticket_id = ticket["id"]

        # --- When: priority is changed to Medium ---
        resp = api_client.patch(
            f"/api/tickets/{ticket_id}/priority/",
            {"priority": "Medium", "justification": "Impacto medio"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["priority"] == "Medium"
        assert resp.data["priority_justification"] == "Impacto medio"

        # --- When: an admin response is added ---
        resp = api_client.post(
            f"/api/tickets/{ticket_id}/responses/",
            {"text": "Estamos revisando tu caso", "admin_id": "admin-1"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["text"] == "Estamos revisando tu caso"

        # --- Then: responses endpoint lists the response ---
        resp = api_client.get(f"/api/tickets/{ticket_id}/responses/")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]["text"] == "Estamos revisando tu caso"

    def test_full_flow_with_all_priority_levels(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Escalate priority through Low → Medium → High."""
        ticket = create_ticket()
        ticket_id = ticket["id"]

        for priority in ("Low", "Medium", "High"):
            resp = api_client.patch(
                f"/api/tickets/{ticket_id}/priority/",
                {"priority": priority, "justification": f"Escalado a {priority}"},
                format="json",
            )
            assert resp.status_code == 200
            assert resp.data["priority"] == priority

    def test_multiple_responses_on_ticket(
        self, api_client, mock_auth_admin, mock_event_publisher, create_ticket
    ):
        """Multiple admin responses are stored and returned in order."""
        ticket = create_ticket()
        ticket_id = ticket["id"]

        texts = [
            "Primera respuesta",
            "Segunda respuesta",
            "Tercera respuesta",
        ]
        for text in texts:
            resp = api_client.post(
                f"/api/tickets/{ticket_id}/responses/",
                {"text": text, "admin_id": "admin-1"},
                format="json",
            )
            assert resp.status_code == 201

        resp = api_client.get(f"/api/tickets/{ticket_id}/responses/")
        assert resp.status_code == 200
        assert len(resp.data) == 3
        returned_texts = [r["text"] for r in resp.data]
        assert returned_texts == texts
