# Copilot Instructions — Ticket Service

## Big Picture
- Django 6.0.2 microservice using DDD + EDA; domain rules live in `tickets/domain/`, orchestration in `tickets/application/`, adapters in `tickets/infrastructure/`, HTTP in `tickets/`.
- Core rule: domain entity is framework-agnostic, ORM model is persistence only. Repository maps between them (`tickets/infrastructure/repository.py`).
- Events are first-class: domain entity appends immutable events, use cases publish them via RabbitMQ fanout exchange `tickets` (`tickets/infrastructure/event_publisher.py`).

## Domain Rules To Preserve
- Ticket status state machine: `OPEN -> IN_PROGRESS -> CLOSED` only; closed tickets cannot change status, priority, or accept responses (`tickets/domain/entities.py`).
- Priority transitions: cannot go back to `Unassigned`; justification max length is enforced in domain entity (`tickets/domain/entities.py`).
- XSS defense is layered: serializer `_check_dangerous_input()` and `TicketFactory.create()` both reject HTML tags (`tickets/serializer.py`, `tickets/domain/factories.py`).
- `user_id` is a `CharField` (no FK) to keep service decoupled from user service (`tickets/models.py`).

## Application Flow (use cases)
- ViewSet constructs command DTOs and delegates to use cases; use cases call domain methods, persist via repository, then publish events (`tickets/views.py`, `tickets/application/use_cases.py`).
- Domain exceptions are translated to HTTP responses in the ViewSet (keep controllers thin).

## Auth/Integration Points
- JWT is read from HttpOnly cookie `access_token` by `CookieJWTStatelessAuthentication` (`tickets/infrastructure/cookie_auth.py`).
- RabbitMQ is required for real event publishing; `_translate_event()` maps typed events to JSON payloads (`tickets/infrastructure/event_publisher.py`).

## Tests and Workflows
- Unit (domain only, pytest): `podman-compose exec backend pytest tickets/tests/unit/ -v`
- Integration (Django runner): `podman-compose exec backend python manage.py test tickets.tests.integration --verbosity=2`
- All tests: `podman-compose exec backend python manage.py test tickets --verbosity=2`

## Common Changes
- New use case: add command + use case in `tickets/application/use_cases.py`, keep domain rules in `tickets/domain/entities.py`, publish events, then add integration test in `tickets/tests/integration/`.
- New event: add frozen dataclass in `tickets/domain/events.py`, append in entity, translate in `RabbitMQEventPublisher._translate_event()`.
