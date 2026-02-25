"""
E2E tests — Performance scenarios.

Scenario 4: Verify the API handles 500+ tickets with acceptable response
times and that listing/filtering does not timeout.
"""

import time

import pytest

from tickets.models import Ticket


@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
class TestPerformance:
    """Performance validation with 500+ tickets in the database."""

    TICKET_COUNT = 500
    MAX_RESPONSE_TIME_MS = 500

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _bulk_create_tickets(count, user_id="user-perf"):
        """Insert *count* tickets directly via ORM for speed."""
        tickets = [
            Ticket(
                title=f"Perf ticket {i}",
                description=f"Performance test ticket number {i}",
                status="OPEN",
                user_id=user_id,
            )
            for i in range(count)
        ]
        Ticket.objects.bulk_create(tickets)

    @staticmethod
    def _bulk_create_tickets_multi_user(count, user_ids):
        """Insert tickets distributed across multiple user_ids."""
        tickets = [
            Ticket(
                title=f"Perf ticket {i}",
                description=f"Performance test ticket number {i}",
                status="OPEN",
                user_id=user_ids[i % len(user_ids)],
            )
            for i in range(count)
        ]
        Ticket.objects.bulk_create(tickets)

    # -- tests ------------------------------------------------------------

    def test_list_500_tickets_under_500ms(
        self, api_client, mock_auth_admin, mock_event_publisher
    ):
        """GET /api/tickets/ with 500 tickets responds within threshold."""
        self._bulk_create_tickets(self.TICKET_COUNT)
        assert Ticket.objects.count() >= self.TICKET_COUNT

        start = time.perf_counter()
        resp = api_client.get("/api/tickets/")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert resp.status_code == 200
        assert len(resp.data) >= self.TICKET_COUNT
        assert elapsed_ms < self.MAX_RESPONSE_TIME_MS, (
            f"List endpoint took {elapsed_ms:.1f}ms, "
            f"threshold is {self.MAX_RESPONSE_TIME_MS}ms"
        )

    def test_filter_tickets_no_timeout(
        self, api_client, mock_auth_admin, mock_event_publisher
    ):
        """GET /api/tickets/ completes without timeout under load.

        Even if query-param filtering is not yet implemented the endpoint
        must return successfully and within the time threshold.
        """
        self._bulk_create_tickets(self.TICKET_COUNT)

        start = time.perf_counter()
        resp = api_client.get("/api/tickets/", {"status": "OPEN"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert resp.status_code == 200
        assert elapsed_ms < self.MAX_RESPONSE_TIME_MS, (
            f"Filter endpoint took {elapsed_ms:.1f}ms, "
            f"threshold is {self.MAX_RESPONSE_TIME_MS}ms"
        )

    def test_my_tickets_with_many_tickets(
        self, api_client, mock_auth_admin, mock_event_publisher
    ):
        """GET /api/tickets/my-tickets/{user_id}/ performs well under load."""
        target_user = "user-target"
        user_ids = [target_user, "user-other-1", "user-other-2", "user-other-3"]
        self._bulk_create_tickets_multi_user(self.TICKET_COUNT, user_ids)

        expected_count = self.TICKET_COUNT // len(user_ids)

        start = time.perf_counter()
        resp = api_client.get(f"/api/tickets/my-tickets/{target_user}/")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert resp.status_code == 200
        assert len(resp.data) >= expected_count
        assert elapsed_ms < self.MAX_RESPONSE_TIME_MS, (
            f"my-tickets endpoint took {elapsed_ms:.1f}ms, "
            f"threshold is {self.MAX_RESPONSE_TIME_MS}ms"
        )
