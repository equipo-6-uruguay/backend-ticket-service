# Copilot Instructions — Ticket Service

## Architecture Overview

This is a **Django-based ticket service** using **Domain-Driven Design (DDD)** and **Event-Driven Architecture (EDA)** with clean separation of concerns.

### Core Principle: Domain Model ≠ ORM Model

- **Domain model** (`Ticket` in `tickets/domain/entities.py`): Pure business logic, framework-agnostic dataclass
- **ORM model** (`Ticket` in `tickets/models.py`): Django model for persistence only
- Repositories translate between them; use cases work with domain models exclusively

## Layer Architecture

### 1. **Domain Layer** (`tickets/domain/`)
- **Entities**: `Ticket` dataclass with state machine: `OPEN` → `IN_PROGRESS` → `CLOSED` (enforced by `change_status()` method)
- **Events**: Immutable frozen dataclasses (`TicketCreated`, `TicketStatusChanged`, `TicketPriorityChanged`, `TicketResponseAdded`)
- **Exceptions**: Domain-specific hierarchy (`DomainException` → `TicketAlreadyClosed`, `InvalidTicketStateTransition`, etc.)
- **Repository Interface** (`repositories.py`): Abstract `TicketRepository` with `save()`, `find_by_id()`, `find_all()`, `delete()`
- **EventPublisher Interface** (`event_publisher.py`): Abstract publisher with `publish(event: DomainEvent)`
- **Factory Pattern** (`factories.py`): `TicketFactory.create()` validates all inputs (no empty strings, HTML injection prevention)

### 2. **Application Layer** (`tickets/application/`)
- **Commands**: Data objects (`CreateTicketCommand`, `ChangeTicketStatusCommand`, `ChangeTicketPriorityCommand`, `AddTicketResponseCommand`)
- **Use Cases**: Orchestrate domain operations:
  - Instantiate entity/factory → Apply business logic → Persist via repository → Publish events
  - Never contain direct business rules (those live in domain entities)
  - Always handle `DomainException` and convert to HTTP status codes

### 3. **Infrastructure Layer** (`tickets/infrastructure/`)
- **DjangoTicketRepository**: Implements `TicketRepository` with ORM operations; methods `to_domain()`, `to_django_model()` for translation
- **RabbitMQEventPublisher**: Implements `EventPublisher`; `_translate_event()` converts domain events to JSON messages
- **Authentication**: `cookie_auth.py` for request validation

### 4. **Presentation Layer** (`tickets/`)
- **ViewSet** (`views.py`): Thin controllers — validate HTTP input → create `Command` → execute use case → catch `DomainException` → return HTTP response
- **Serializers** (`serializer.py`): DRF serializers validate and deserialize request data (XSS protection via `validate_field()` methods)

## Critical Patterns & Rules

### State Machine Rule
```python
# Ticket can ONLY transition: OPEN → IN_PROGRESS → CLOSED
# Cannot go backwards; cannot change CLOSED ticket
ticket.change_status(new_status)  # Raises InvalidTicketStateTransition or TicketAlreadyClosed
```

### Validation Pattern
- **Factory validates at creation**: `TicketFactory.create(title, description, user_id)` checks for empty strings, HTML injection
- **Serializers validate at HTTP**: `TicketSerializer.validate_title()` uses `_check_dangerous_input()`
- **Use cases catch domain exceptions** and convert to HTTP responses (400, 403, 404, 500)

### XSS Prevention
- HTML tags and scripts detected in title/description → `DangerousInputError` raised
- Check implementation: `tickets/serializer.py`, `_check_dangerous_input()`, regex pattern `<[^>]*>`

### Microservice Loose Coupling
- `user_id` is `CharField`, **not a ForeignKey** — allows independent user-service database
- No direct coupling to authentication service; validated via `cookie_auth.py`

### Event Publication Pattern
1. Use case executes business logic on domain entity
2. Entity generates immutable `DomainEvent` (stored in `_domain_events` list)
3. Use case extracts events and publishes via `event_publisher.publish()`
4. RabbitMQ consumer listens on `tickets` exchange (fanout, durable)

## Testing Strategy

### Unit Tests (pytest — domain layer only)
```bash
podman-compose exec backend pytest tickets/tests/unit/ -v
```
- Test pure business logic without Django, DB, or RabbitMQ
- Files: `test_ticket_entity.py`, `test_use_cases.py`, `test_events.py`, `test_factory.py`
- No mocks needed; instantiate entities directly

### Integration Tests (Django test runner)
```bash
podman-compose exec backend python manage.py test tickets.tests.integration --verbosity=2
```
- Test repository persistence, API endpoints, workflows
- Use `TestCase` with transaction rollback
- Files: `test_ticket_repository.py`, `test_ticket_responses_api.py`, `test_ticket_workflow.py`

### Running All Tests
```bash
podman-compose exec backend python manage.py test tickets --verbosity=2
```

## Key Files Reference

| File | Purpose | Key Patterns |
|------|---------|--------------|
| `tickets/domain/entities.py` | Ticket business logic | State machine, validation, event generation |
| `tickets/application/use_cases.py` | Orchestration | Dependency injection, command pattern |
| `tickets/infrastructure/repository.py` | ORM adapter | Domain ↔ Django model translation |
| `tickets/infrastructure/event_publisher.py` | Event broadcast | JSON serialization, RabbitMQ fanout |
| `tickets/views.py` | HTTP controller | Exception handling, thin layer |
| `tickets/serializer.py` | HTTP validation | XSS prevention, DRF integration |

## Common Tasks

### Adding a New Use Case
1. Create `Command` dataclass in `use_cases.py`
2. Create `UseCase` class with `__init__(repository, event_publisher)` and `execute(command: Command)`
3. Inside: entity logic → repository.save() → publish events
4. Add test in `tests/integration/test_ticket_workflow.py`

### Adding a Domain Rule
1. Add validation to `Ticket.method()` in `entities.py`
2. Raise appropriate `DomainException` if rule violated
3. Catch exception in use case and convert to HTTP status
4. Add unit test in `tests/unit/test_ticket_entity.py`

### Adding an Event
1. Create frozen dataclass in `tickets/domain/events.py`
2. Update `Ticket._domain_events` tracking in entity
3. Update `_translate_event()` in `RabbitMQEventPublisher` to handle new event type
4. Publish via use case: `event_publisher.publish(event)`

## Environment & Configuration

- **Django version**: 6.0.2
- **Framework**: Django REST Framework (DRF)
- **Message broker**: RabbitMQ (exchange: `tickets`, type: fanout)
- **Container runtime**: podman-compose
- **env file**: `.env` (required for `TICKET_SERVICE_SECRET_KEY`, `RABBITMQ_HOST`, `RABBITMQ_EXCHANGE_NAME`)
