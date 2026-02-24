# Branch: refactor/disable-generic-crud-methods

## Issue Metadata
- **Issue Title:** [Feature] Disable inherited PUT/PATCH/DELETE methods on TicketViewSet
- **Issue Number:** #1
- **Labels:** feature, backend, priority:high, risk:high, role:admin, qa
- **Priority:** Alta
- **Type:** Feature (architectural hardening)
- **Related User Story:** us-001 — Deshabilitar métodos CRUD genéricos heredados
- **Acceptance Criteria:** 6 Gherkin scenarios (PUT→405, PATCH→405, DELETE→405, custom /status/ works, custom /priority/ works, custom /responses/ works)
- **Components Affected:** `tickets/views.py` (presentation layer only)

## Overview

`TicketViewSet` currently inherits from `viewsets.ModelViewSet`, which bundles `UpdateModelMixin` and `DestroyModelMixin`. This silently exposes `PUT`, `PATCH` (generic), and `DELETE` on `/api/tickets/{pk}/`, allowing clients to bypass domain rules (state machine, priority transitions, XSS validation), use case orchestration, and event publishing.

The goal is to **remove these unwanted capabilities at the inheritance level** by replacing `ModelViewSet` with an explicit composition of only the needed mixins: `CreateModelMixin`, `RetrieveModelMixin`, `ListModelMixin`, and `GenericViewSet`. This is architecturally cleaner than overriding methods with 405 — it eliminates the capability entirely rather than patching over it.

## Assumptions

- The only legitimate mutation paths are the existing custom actions: `change_status`, `change_priority`, `responses`, and `my_tickets`.
- `perform_create()` is already properly overridden and will continue to work with `CreateModelMixin`.
- DRF's `DefaultRouter` dynamically inspects viewset methods to decide which HTTP verbs to wire — removing the mixins means the router won't register PUT/PATCH/DELETE on the detail endpoint.
- No external consumers depend on the generic PUT/PATCH/DELETE endpoints (if they did, they were already bypassing domain rules).
- OpenAPI/Swagger schema will automatically reflect the removal since DRF schema generation inspects available actions.

## Architecture Impact

**Single layer affected:** Presentation (`tickets/views.py`).

No changes to domain, application, infrastructure, or persistence layers. This is a pure access-control hardening at the HTTP boundary.

## Design Strategy

### SOLID Approach

| Principle | Analysis |
|-----------|----------|
| **SRP** | The ViewSet is already a thin controller. Removing unused mixins sharpens its responsibility: accept HTTP → delegate to use cases → return HTTP responses. |
| **OCP** | Mixin composition is inherently OCP-friendly. If a legitimate update use case is ever needed, a new mixin or custom action can be added without modifying existing code. |
| **DIP** | No change — the ViewSet already depends on abstract use case interfaces. |
| **ISP** | This change **is** ISP in practice. By removing `UpdateModelMixin` and `DestroyModelMixin`, the ViewSet no longer exposes interface methods it should never fulfill. |
| **LSP** | Safe. We are narrowing the interface by changing the base class, not violating contracts — the new base (`GenericViewSet`) has no expectation of update/destroy. |

### GOF Patterns

**None required.** The existing architecture already employs:
- **Command** pattern (use case command DTOs)
- **Repository** pattern (domain ↔ persistence mapping)
- **Factory** pattern (`TicketFactory.create()`)
- **Observer** pattern (domain events → RabbitMQ publisher)

This change is purely subtractive — removing inherited behavior. Simple mixin composition is the correct and sufficient mechanism. No new patterns needed.

### Layering Decisions

| Layer | Impact |
|-------|--------|
| **Domain** (`tickets/domain/`) | No changes. Entity, events, exceptions untouched. |
| **Application** (`tickets/application/`) | No changes. Use cases untouched. |
| **Infrastructure** (`tickets/infrastructure/`) | No changes. Repository, event publisher, auth untouched. |
| **Presentation** (`tickets/views.py`) | Inheritance chain modified. Only file with code changes. |

**Dependency direction remains correct:** Presentation → Application → Domain. Infrastructure implements domain ports.

This change **reinforces** the layered boundary by ensuring the presentation layer cannot accidentally provide a bypass path to ORM-level mutations.

### Testability Plan

| Category | What | How |
|----------|------|-----|
| **Unit — Structural** | Verify ViewSet class does NOT include `UpdateModelMixin` / `DestroyModelMixin` in MRO | `assertNotIn` on `TicketViewSet.__mro__` |
| **Unit — Behavioral** | Verify `update`, `partial_update`, `destroy` are not resolvable actions | Check `hasattr` / action map |
| **Integration — 405 responses** | PUT, PATCH, DELETE to `/api/tickets/{pk}/` return 405 | `APIClient` HTTP requests |
| **Integration — Data integrity** | Ticket is NOT modified/deleted after rejected requests | DB assertion after 405 |
| **Integration — Custom endpoints** | `/status/`, `/priority/`, `/responses/` still work correctly | `APIClient` + mock event publisher |
| **Mocks** | `CookieJWTStatelessAuthentication` bypassed in tests; `RabbitMQEventPublisher` mocked | `@patch` decorators / DRF test auth |

## Commits

---

### Commit 1: `refactor(views): replace ModelViewSet with explicit mixin composition`

**Purpose**

Remove `UpdateModelMixin` and `DestroyModelMixin` from the ViewSet inheritance chain so that PUT, PATCH (generic), and DELETE are not wired by the router. This is the actual security/architectural fix.

**Files**

Modified:
- `tickets/views.py`

**Changes**

1. Add imports for `CreateModelMixin`, `RetrieveModelMixin`, `ListModelMixin` from `rest_framework.mixins`.
2. Change class declaration from:
   ```python
   class TicketViewSet(viewsets.ModelViewSet):
   ```
   to:
   ```python
   class TicketViewSet(
       CreateModelMixin,
       RetrieveModelMixin,
       ListModelMixin,
       viewsets.GenericViewSet,
   ):
   ```
3. Update the class docstring to document that generic update/destroy are intentionally excluded and why (DDD integrity).

**Tests**

No tests in this commit — tests come in Commit 2 to keep the diff focused. The refactor is semantically safe because we are only removing capabilities, not modifying existing behavior.

---

### Commit 2: `test(views): verify disabled PUT/PATCH/DELETE and custom endpoint integrity`

**Purpose**

Add comprehensive unit and integration tests covering all 6 Gherkin acceptance criteria. Confirms that generic CRUD methods return 405, that data integrity is preserved after rejected requests, and that all custom endpoints continue to function correctly with proper domain event publishing.

**Files**

Modified:
- `tickets/tests/unit/test_views.py`
- `tickets/tests/integration/test_ticket_workflow.py`

**Changes**

**Unit tests** (in `test_views.py`):

1. `test_viewset_does_not_include_update_mixin` — Structural check: `UpdateModelMixin` not in `TicketViewSet.__mro__`.
2. `test_viewset_does_not_include_destroy_mixin` — Structural check: `DestroyModelMixin` not in `TicketViewSet.__mro__`.
3. `test_viewset_has_no_update_method_from_mixin` — Verify `update` action is not mapped.
4. `test_viewset_has_no_partial_update_method_from_mixin` — Verify `partial_update` action is not mapped.
5. `test_viewset_has_no_destroy_method_from_mixin` — Verify `destroy` action is not mapped.

**Integration tests** (in `test_ticket_workflow.py`):

6. `test_put_generic_returns_405_and_ticket_unchanged` — Create a ticket, send PUT to `/api/tickets/{id}/`, assert 405, assert ticket data unchanged in DB.
7. `test_patch_generic_returns_405_and_ticket_unchanged` — Create a ticket, send PATCH to `/api/tickets/{id}/`, assert 405, assert ticket data unchanged in DB.
8. `test_delete_generic_returns_405_and_ticket_intact` — Create a ticket, send DELETE to `/api/tickets/{id}/`, assert 405, assert ticket still exists in DB.
9. `test_custom_status_endpoint_still_works_after_refactor` — Create ticket, PATCH `/api/tickets/{id}/status/` with `{"status": "IN_PROGRESS"}`, assert 200, assert status changed, assert `TicketStatusChanged` event published.
10. `test_custom_priority_endpoint_still_works_after_refactor` — Create ticket, PATCH `/api/tickets/{id}/priority/` with `{"priority": "High", "justification": "Urgente"}`, assert 200, assert priority changed, assert `TicketPriorityChanged` event published.
11. `test_custom_responses_endpoint_still_works_after_refactor` — Create ticket, POST `/api/tickets/{id}/responses/` with `{"text": "Resuelto", "admin_id": "admin1"}`, assert 201, assert response created, assert `TicketResponseAdded` event published.

**Tests**

This commit IS the tests. All 6 Gherkin scenarios are covered:
- Scenarios 1–3: Tests 6, 7, 8 (405 + data integrity)
- Scenario 4: Test 9 (custom /status/)
- Scenario 5: Test 10 (custom /priority/)
- Scenario 6: Test 11 (custom /responses/)

Structural unit tests (1–5) provide an additional safety net at the class level.

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **External consumers depend on generic PUT/PATCH/DELETE** | Low — these endpoints bypassed domain rules, so any usage was already incorrect | Integration tests confirm 405; review API consumers if any exist |
| **DRF schema/docs break** | Very low — DRF schema auto-generates from available actions | Verify Swagger/OpenAPI output manually after merge |
| **Custom PATCH actions affected** | None — `@action(methods=["patch"])` decorators register their own URL patterns, independent of the detail route | Integration tests 9–11 explicitly verify |
| **Third-party DRF middleware expects ModelViewSet** | Very low — middleware should work with GenericViewSet | Run full test suite |
| **`perform_create` stops working** | None — `CreateModelMixin` provides `create()` which calls `perform_create()` | Existing test `test_viewset_uses_create_use_case_on_create` already covers this |

## Rollback Strategy

Revert the single-line inheritance change in `tickets/views.py` back to `viewsets.ModelViewSet`. This is a safe one-line revert. Tests from Commit 2 would need to be removed or inverted, but the rollback is operationally trivial.

```bash
git revert HEAD~2..HEAD
```

Or simply change the class declaration back to `viewsets.ModelViewSet` and remove the mixin imports.

## Clarification Required

None. All scope is clear from the Issue.

---

## Issue Reference

Closes #1
