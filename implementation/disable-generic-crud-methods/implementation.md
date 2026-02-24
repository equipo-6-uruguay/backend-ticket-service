# Implementation: Disable inherited PUT/PATCH/DELETE methods on TicketViewSet

## Branch

`refactor/disable-generic-crud-methods`

## Issue

Closes #1

## Goal

Remove unwanted generic `PUT`, `PATCH`, and `DELETE` capabilities from `TicketViewSet` by replacing `ModelViewSet` with an explicit composition of only the needed mixins (`CreateModelMixin`, `RetrieveModelMixin`, `ListModelMixin`, `GenericViewSet`). This eliminates the possibility of clients bypassing domain rules, use case orchestration, and event publishing through inherited DRF CRUD methods.

---

## Prerequisites

- Python 3.12+
- Django 6.0.2
- Django REST Framework (already installed)
- Podman / podman-compose (for running containerized tests)

No new dependencies are required. This change is purely subtractive at the inheritance level.

---

## Commit 1: `refactor(views): replace ModelViewSet with explicit mixin composition`

### Purpose

Remove `UpdateModelMixin` and `DestroyModelMixin` from the `TicketViewSet` inheritance chain so that generic PUT, PATCH, and DELETE are not wired by the DRF router. This is the actual security/architectural fix.

### Files Created

_None._

### Files Modified

#### `tickets/views.py`

```python
"""
ViewSet refactorizado para usar DDD/EDA.
Las vistas ahora son thin controllers que delegan a casos de uso.
NO contienen lógica de negocio, NO acceden directamente al ORM.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin, RetrieveModelMixin, ListModelMixin
from rest_framework.response import Response
from django.db import transaction

from .models import Ticket, TicketResponse
from .serializer import TicketSerializer, TicketResponseSerializer
from .application.use_cases import (
    CreateTicketUseCase,
    CreateTicketCommand,
    ChangeTicketStatusUseCase,
    ChangeTicketStatusCommand,
    AddTicketResponseUseCase,
    AddTicketResponseCommand,
    ChangeTicketPriorityUseCase,
    ChangeTicketPriorityCommand,
)
from .infrastructure.repository import DjangoTicketRepository
from .infrastructure.event_publisher import RabbitMQEventPublisher
from .domain.exceptions import (
    DomainException,
    TicketAlreadyClosed,
    InvalidTicketData,
    DangerousInputError,
    EmptyResponseError,
    InvalidPriorityTransition,
)


class TicketViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet refactorizado siguiendo principios DDD/EDA.

    Hereda explícitamente de CreateModelMixin, RetrieveModelMixin,
    ListModelMixin y GenericViewSet. Los mixins UpdateModelMixin y
    DestroyModelMixin están excluidos INTENCIONALMENTE para impedir
    que clientes utilicen PUT/PATCH/DELETE genéricos, los cuales
    evadirían la máquina de estados del dominio, las transiciones
    de prioridad, la validación XSS y la publicación de eventos.

    Las únicas vías de mutación legítimas son las acciones custom:
      - PATCH /api/tickets/{id}/status/    → change_status
      - PATCH /api/tickets/{id}/priority/  → change_priority
      - POST  /api/tickets/{id}/responses/ → responses

    Responsabilidades:
    - Validar entrada HTTP
    - Ejecutar casos de uso
    - Traducir respuestas de dominio a HTTP
    - Manejar excepciones de dominio

    NO responsable de:
    - Lógica de negocio (en entidades y casos de uso)
    - Persistencia directa (delegada al repositorio)
    - Publicación de eventos (delegada al event publisher)
    """

    queryset = Ticket.objects.all().order_by("-created_at")
    serializer_class = TicketSerializer

    def __init__(self, *args, **kwargs):
        """Inicializa las dependencias (repositorio, event publisher, use cases)."""
        super().__init__(*args, **kwargs)

        # Inyección de dependencias
        self.repository = DjangoTicketRepository()
        self.event_publisher = RabbitMQEventPublisher()

        # Casos de uso
        self.create_ticket_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        self.change_status_use_case = ChangeTicketStatusUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        self.add_response_use_case = AddTicketResponseUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        self.change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )

    def perform_create(self, serializer):
        """
        Crea un ticket ejecutando el caso de uso correspondiente.
        NO guarda directamente, delega al caso de uso.
        """
        try:
            # Crear comando desde los datos validados
            command = CreateTicketCommand(
                title=serializer.validated_data['title'],
                description=serializer.validated_data['description'],
                user_id=serializer.validated_data['user_id']
            )

            # Ejecutar caso de uso (maneja dominio, persistencia y eventos)
            domain_ticket = self.create_ticket_use_case.execute(command)

            # Convertir entidad de dominio a modelo Django para serialización
            # (DRF espera una instancia del modelo Django)
            django_ticket = self.repository.to_django_model(domain_ticket)
            serializer.instance = django_ticket

        except InvalidTicketData as e:
            # Convertir excepción de dominio a error de validación DRF
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    @action(detail=True, methods=["patch"], url_path="status")
    def change_status(self, request, pk=None):
        """
        Cambia el estado de un ticket ejecutando el caso de uso.
        Aplica reglas de negocio del dominio.
        """
        new_status = request.data.get("status")

        # Validación de entrada HTTP
        if not new_status:
            return Response(
                {"error": "El campo 'status' es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Crear comando
            command = ChangeTicketStatusCommand(
                ticket_id=int(pk),
                new_status=new_status
            )

            # Ejecutar caso de uso
            domain_ticket = self.change_status_use_case.execute(command)

            # Convertir entidad de dominio a modelo Django para serialización
            django_ticket = self.repository.to_django_model(domain_ticket)

            return Response(
                TicketSerializer(django_ticket).data,
                status=status.HTTP_200_OK,
            )

        except TicketAlreadyClosed as e:
            # Ticket cerrado: regla de negocio violada
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as e:
            # Estado inválido o ticket no encontrado
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DomainException as e:
            # Otras excepciones de dominio
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["patch"], url_path="priority")
    def change_priority(self, request, pk=None):
        """
        Cambia la prioridad de un ticket ejecutando el caso de uso.
        Aplica reglas de negocio del dominio (transiciones válidas, permisos).

        PATCH /api/tickets/{id}/priority/

        Body params:
            - priority (str, requerido): Nueva prioridad del ticket.
            - justification (str, opcional): Justificación del cambio.
            - user_role (str, opcional): Rol del usuario que solicita el cambio.

        Errores:
            - 400: Campo 'priority' ausente, ticket cerrado, transición inválida.
            - 403: Permiso denegado (excepción de dominio).
        """
        new_priority = request.data.get("priority")
        justification = request.data.get("justification")
        # Read role from JWT token and map to the value the use case expects
        jwt_role = ''
        if hasattr(request.user, 'token'):
            jwt_role = request.user.token.get('role', '')
        # Map ADMIN role to 'Administrador' which the use case expects for authorization
        user_role = 'Administrador' if jwt_role.upper() == 'ADMIN' else jwt_role

        # Validación de entrada HTTP
        if not new_priority:
            return Response(
                {"error": "El campo 'priority' es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Crear comando
            command = ChangeTicketPriorityCommand(
                ticket_id=int(pk),
                new_priority=new_priority
            )
            command.justification = justification
            command.user_role = user_role

            # Ejecutar caso de uso
            domain_ticket = self.change_priority_use_case.execute(command)

            # Convertir entidad de dominio a modelo Django para serialización
            django_ticket = self.repository.to_django_model(domain_ticket)

            return Response(
                TicketSerializer(django_ticket).data,
                status=status.HTTP_200_OK,
            )

        except (TicketAlreadyClosed, InvalidPriorityTransition) as e:
            # Regla de negocio violada: ticket cerrado o transición de prioridad inválida
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as e:
            # Valor inválido o ticket no encontrado
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DomainException as e:
            # Otras excepciones de dominio (ej. permiso denegado)
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )

    @action(detail=False, methods=["get"], url_path="my-tickets/(?P<user_id>[^/.]+)")
    def my_tickets(self, request, user_id=None):
        """
        Obtiene todos los tickets de un usuario específico.

        GET /api/tickets/my-tickets/{user_id}/

        Args:
            user_id: ID del usuario cuyos tickets se quieren obtener

        Returns:
            Lista de tickets del usuario
        """
        try:
            # Filtrar tickets por user_id
            tickets = Ticket.objects.filter(user_id=user_id).order_by("-created_at")

            # Serializar y retornar
            serializer = TicketSerializer(tickets, many=True)
            return Response(
                serializer.data,
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"Error al obtener tickets: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get", "post"], url_path="responses")
    def responses(self, request, pk: str | None = None) -> Response:
        """Punto de entrada para respuestas de administrador en un ticket.

        GET  /api/tickets/{id}/responses/ — Lista respuestas (HU-1.2).
        POST /api/tickets/{id}/responses/ — Crea respuesta de admin (HU-1.1).

        Args:
            request: Objeto HTTP de DRF.
            pk: ID del ticket.

        Returns:
            Response con lista de respuestas o la respuesta creada.
        """
        if request.method == "GET":
            return self._list_responses(request, pk)
        return self._create_response(request, pk)

    def _list_responses(self, request, ticket_id: str | None) -> Response:
        """Lista respuestas de un ticket en orden cronológico ascendente.

        Aplica control de visibilidad (HU-1.2): solo el creador del ticket
        y los usuarios con rol ADMIN pueden leer las respuestas.

        Args:
            request: Objeto HTTP de DRF.
            ticket_id: ID del ticket cuyas respuestas se listan.

        Returns:
            Response 200 con lista serializada, o 403 si el acceso está
            denegado, o 404 si el ticket no existe.
        """
        # C4 — Validar visibilidad: solo creador del ticket o ADMIN
        user_id: str = str(getattr(request.user, 'id', ''))
        user_role: str = ''
        if hasattr(request.user, 'token'):
            user_role = request.user.token.get('role', '')

        is_admin = user_role.upper() == "ADMIN"

        if not is_admin:
            # Verificar que el solicitante es el creador del ticket
            try:
                ticket = Ticket.objects.get(pk=ticket_id)
            except Ticket.DoesNotExist:
                return Response(
                    {"error": f"Ticket {ticket_id} no encontrado"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if str(ticket.user_id) != str(user_id):
                return Response(
                    {"error": "No tienes permiso para ver las respuestas de este ticket"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        responses = TicketResponse.objects.filter(
            ticket_id=ticket_id,
        ).order_by("created_at")
        serializer = TicketResponseSerializer(responses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _create_response(self, request, ticket_id: str | None) -> Response:
        """Crea una respuesta de administrador delegando al caso de uso.

        Flujo:
        1. Valida que el solicitante tiene rol ADMIN (cabecera X-User-Role).
        2. Valida entrada con ``TicketResponseSerializer``.
        3. Ejecuta ``AddTicketResponseUseCase`` (reglas de dominio + evento).
        4. Persiste ``TicketResponse`` en el modelo Django.
        5. Retorna la respuesta creada.

        Args:
            request: Objeto HTTP de DRF con ``text`` y ``admin_id``.
            ticket_id: ID del ticket al que se agrega la respuesta.

        Returns:
            Response 201 con la respuesta creada, 403 si no es ADMIN,
            o 400 ante error de dominio.

        Raises:
            No lanza excepciones; todas se traducen a respuestas HTTP.
        """
        # C2 — Validar que el solicitante es ADMIN
        user_role: str = ''
        if hasattr(request.user, 'token'):
            user_role = request.user.token.get('role', '')
        if user_role.upper() != "ADMIN":
            return Response(
                {"error": "Solo los administradores pueden responder tickets"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TicketResponseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        admin_id: str = serializer.validated_data["admin_id"]
        text: str = serializer.validated_data["text"]

        try:
            with transaction.atomic():
                # C5 / B3 — Persistir primero para obtener el response_id real
                # que se incluirá en el evento ticket.response_added.
                ticket = Ticket.objects.get(pk=ticket_id)
                response_obj = TicketResponse.objects.create(
                    ticket=ticket,
                    admin_id=admin_id,
                    text=text,
                )

                # Ejecutar caso de uso con el response_id ya conocido.
                # Si el dominio rechaza la operación, la transacción hace
                # rollback y el registro ORM se elimina automáticamente.
                command = AddTicketResponseCommand(
                    ticket_id=int(ticket_id),
                    text=text,
                    admin_id=admin_id,
                    response_id=response_obj.id,
                )
                self.add_response_use_case.execute(command)

            output_serializer = TicketResponseSerializer(response_obj)
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)

        except Ticket.DoesNotExist:
            return Response(
                {"error": f"Ticket {ticket_id} no encontrado"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TicketAlreadyClosed as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except EmptyResponseError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DomainException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
```

### Files Deleted

_None._

### Execution Steps

```bash
git checkout -b refactor/disable-generic-crud-methods
git add tickets/views.py
git commit -m "refactor(views): replace ModelViewSet with explicit mixin composition"
```

---

## Commit 2: `test(views): verify disabled PUT/PATCH/DELETE and custom endpoint integrity`

### Purpose

Add comprehensive unit and integration tests covering all 6 Gherkin acceptance criteria. Confirms that generic CRUD methods return 405, that data integrity is preserved after rejected requests, and that all custom endpoints continue to function correctly with proper domain event publishing.

### Files Created

_None._

### Files Modified

#### `tickets/tests/unit/test_views.py`

```python
"""
Tests de la capa de presentación (ViewSet).
Prueban la integración HTTP con casos de uso.
"""

from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework.request import Request
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework import status
from rest_framework.mixins import UpdateModelMixin, CreateModelMixin, RetrieveModelMixin, ListModelMixin
from rest_framework.viewsets import GenericViewSet
from unittest.mock import Mock, patch

from tickets.models import Ticket as DjangoTicket
from tickets.domain.entities import Ticket as DomainTicket
from tickets.domain.exceptions import TicketAlreadyClosed, InvalidTicketData, InvalidPriorityTransition, DomainException
from tickets.views import TicketViewSet
from tickets.serializer import TicketSerializer
from datetime import datetime


class TestTicketViewSetMixinComposition(TestCase):
    """Structural tests: verify TicketViewSet inherits only the intended mixins."""

    def test_viewset_does_not_include_update_mixin(self):
        """UpdateModelMixin must NOT be in the MRO — generic PUT/PATCH disabled."""
        from rest_framework.mixins import UpdateModelMixin
        self.assertNotIn(
            UpdateModelMixin,
            TicketViewSet.__mro__,
            "TicketViewSet must NOT inherit UpdateModelMixin",
        )

    def test_viewset_does_not_include_destroy_mixin(self):
        """DestroyModelMixin must NOT be in the MRO — generic DELETE disabled."""
        from rest_framework.mixins import DestroyModelMixin
        self.assertNotIn(
            DestroyModelMixin,
            TicketViewSet.__mro__,
            "TicketViewSet must NOT inherit DestroyModelMixin",
        )

    def test_viewset_has_no_update_method_from_mixin(self):
        """The 'update' action must not be resolvable on TicketViewSet."""
        viewset = TicketViewSet()
        actions = getattr(viewset, 'action_map', {})
        self.assertNotIn('update', dir(UpdateModelMixin))
        # More robust: ensure no 'update' method inherited from UpdateModelMixin
        self.assertFalse(
            hasattr(viewset, 'update') and 'UpdateModelMixin' in str(type(viewset).update),
            "TicketViewSet must not expose an 'update' action from UpdateModelMixin",
        )

    def test_viewset_has_no_partial_update_method_from_mixin(self):
        """The 'partial_update' action must not be resolvable on TicketViewSet."""
        viewset = TicketViewSet()
        self.assertFalse(
            hasattr(viewset, 'partial_update') and 'UpdateModelMixin' in str(type(viewset).partial_update),
            "TicketViewSet must not expose a 'partial_update' action from UpdateModelMixin",
        )

    def test_viewset_has_no_destroy_method_from_mixin(self):
        """The 'destroy' action must not be resolvable on TicketViewSet."""
        viewset = TicketViewSet()
        self.assertFalse(
            hasattr(viewset, 'destroy'),
            "TicketViewSet must not expose a 'destroy' action",
        )

    def test_viewset_includes_create_mixin(self):
        """CreateModelMixin must be in the MRO — POST /api/tickets/ enabled."""
        self.assertIn(
            CreateModelMixin,
            TicketViewSet.__mro__,
            "TicketViewSet must inherit CreateModelMixin",
        )

    def test_viewset_includes_retrieve_mixin(self):
        """RetrieveModelMixin must be in the MRO — GET /api/tickets/{id}/ enabled."""
        self.assertIn(
            RetrieveModelMixin,
            TicketViewSet.__mro__,
            "TicketViewSet must inherit RetrieveModelMixin",
        )

    def test_viewset_includes_list_mixin(self):
        """ListModelMixin must be in the MRO — GET /api/tickets/ enabled."""
        self.assertIn(
            ListModelMixin,
            TicketViewSet.__mro__,
            "TicketViewSet must inherit ListModelMixin",
        )

    def test_viewset_inherits_generic_viewset(self):
        """GenericViewSet must be the base — not ModelViewSet."""
        self.assertIn(
            GenericViewSet,
            TicketViewSet.__mro__,
            "TicketViewSet must inherit GenericViewSet",
        )
        from rest_framework.viewsets import ModelViewSet
        self.assertNotIn(
            ModelViewSet,
            TicketViewSet.__mro__,
            "TicketViewSet must NOT inherit ModelViewSet",
        )


class TestTicketViewSet(TestCase):
    """Tests del ViewSet con nueva arquitectura DDD."""

    def setUp(self):
        """Configurar para cada test."""
        self.factory = APIRequestFactory()

    def _make_drf_request(self, wsgi_request):
        """Envuelve un WSGIRequest en un DRF Request para llamadas directas a métodos del ViewSet."""
        return Request(wsgi_request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

    def test_viewset_uses_create_use_case_on_create(self):
        """ViewSet ejecuta CreateTicketUseCase al crear ticket."""
        viewset = TicketViewSet()

        # Mockear el caso de uso
        mock_use_case = Mock()
        mock_domain_ticket = DomainTicket(
            id=123,
            title="Test",
            description="Desc",
            status=DomainTicket.OPEN,
            created_at=datetime.now()
        )
        mock_use_case.execute.return_value = mock_domain_ticket
        viewset.create_ticket_use_case = mock_use_case

        # Crear ticket Django para serializer
        DjangoTicket.objects.create(
            id=123,
            title="Test",
            description="Desc",
            status="OPEN"
        )

        # Simular perform_create
        serializer = TicketSerializer(data={"title": "Test", "description": "Desc"})
        serializer.is_valid()

        viewset.perform_create(serializer)

        # Verificar que se ejecutó el caso de uso
        mock_use_case.execute.assert_called_once()

    def test_viewset_handles_invalid_ticket_data_exception(self):
        """ViewSet maneja InvalidTicketData y devuelve error de validación."""
        viewset = TicketViewSet()

        # Mockear caso de uso para que lance excepción
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = InvalidTicketData("Título vacío")
        viewset.create_ticket_use_case = mock_use_case

        serializer = TicketSerializer(data={"title": "", "description": "Desc"})
        serializer.is_valid()

        # Debe lanzar ValidationError
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            viewset.perform_create(serializer)

    def test_change_status_endpoint_executes_use_case(self):
        """Endpoint change_status ejecuta ChangeTicketStatusUseCase."""
        # Crear ticket en BD
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        # Mockear caso de uso
        mock_use_case = Mock()
        mock_domain_ticket = DomainTicket(
            id=django_ticket.id,
            title="Test",
            description="Desc",
            status=DomainTicket.IN_PROGRESS,
            created_at=django_ticket.created_at
        )
        mock_use_case.execute.return_value = mock_domain_ticket
        viewset.change_status_use_case = mock_use_case

        # Crear request
        request = self.factory.patch('', {"status": "IN_PROGRESS"})

        # Ejecutar action
        response = viewset.change_status(request, pk=django_ticket.id)

        # Verificar que se ejecutó el caso de uso
        mock_use_case.execute.assert_called_once()
        assert response.status_code == status.HTTP_200_OK

    def test_change_status_handles_ticket_already_closed(self):
        """ViewSet maneja TicketAlreadyClosed y devuelve 400."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="CLOSED"
        )

        viewset = TicketViewSet()

        # Mockear caso de uso para que lance excepción
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = TicketAlreadyClosed(django_ticket.id)
        viewset.change_status_use_case = mock_use_case

        request = self.factory.patch('', {"status": "OPEN"})

        response = viewset.change_status(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cerrado" in str(response.data['error']).lower()

    def test_change_status_requires_status_field(self):
        """Endpoint change_status requiere el campo 'status'."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()
        request = self.factory.patch('', {})  # Sin status

        response = viewset.change_status(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "requerido" in str(response.data['error']).lower()

    def test_change_status_handles_invalid_status(self):
        """ViewSet maneja estado inválido y devuelve 400."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        # Mockear caso de uso para que lance ValueError
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = ValueError("Estado inválido")
        viewset.change_status_use_case = mock_use_case

        request = self.factory.patch('', {"status": "INVALID"})

        response = viewset.change_status(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # ── Phase 5: change_priority endpoint tests (RED) ──────────────────

    def test_change_priority_endpoint_executes_use_case(self):
        """Endpoint change_priority ejecuta ChangePriorityUseCase."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_domain_ticket = DomainTicket(
            id=django_ticket.id,
            title="Test",
            description="Desc",
            status=DomainTicket.OPEN,
            user_id="1",
            created_at=django_ticket.created_at,
            priority="High"
        )
        mock_use_case.execute.return_value = mock_domain_ticket
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {"priority": "High", "user_role": "Administrador"}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        mock_use_case.execute.assert_called_once()
        assert response.status_code == status.HTTP_200_OK

    def test_change_priority_requires_priority_field(self):
        """Endpoint change_priority requiere el campo 'priority'."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        request = self._make_drf_request(self.factory.patch('', {}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "requerido" in str(response.data['error']).lower()

    def test_change_priority_handles_ticket_already_closed(self):
        """ViewSet maneja TicketAlreadyClosed en change_priority y devuelve 400."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="CLOSED"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_use_case.execute.side_effect = TicketAlreadyClosed(django_ticket.id)
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {"priority": "High", "user_role": "Administrador"}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cerrado" in str(response.data['error']).lower()

    def test_change_priority_handles_invalid_priority_transition(self):
        """ViewSet maneja InvalidPriorityTransition y devuelve 400."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_use_case.execute.side_effect = InvalidPriorityTransition(
            "High", "Unassigned", "no se puede volver"
        )
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {"priority": "Unassigned", "user_role": "Administrador"}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_change_priority_handles_permission_denied(self):
        """ViewSet maneja DomainException de permiso y devuelve 403."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_use_case.execute.side_effect = DomainException("Permiso insuficiente")
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {"priority": "High", "user_role": "Usuario"}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_change_priority_passes_justification_to_use_case(self):
        """Endpoint change_priority pasa justificación al caso de uso."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_domain_ticket = DomainTicket(
            id=django_ticket.id,
            title="Test",
            description="Desc",
            status=DomainTicket.OPEN,
            user_id="1",
            created_at=django_ticket.created_at,
            priority="High",
            priority_justification="Urgente"
        )
        mock_use_case.execute.return_value = mock_domain_ticket
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {
            "priority": "High",
            "justification": "Urgente",
            "user_role": "Administrador"
        }))

        response = viewset.change_priority(request, pk=django_ticket.id)

        mock_use_case.execute.assert_called_once()
        call_args = mock_use_case.execute.call_args
        command = call_args[0][0] if call_args[0] else call_args[1].get('command')
        assert command.justification == "Urgente"

    def test_change_priority_returns_updated_priority_in_response(self):
        """Endpoint change_priority devuelve prioridad actualizada en respuesta."""
        django_ticket = DjangoTicket.objects.create(
            title="Test",
            description="Desc",
            status="OPEN"
        )

        viewset = TicketViewSet()

        mock_use_case = Mock()
        mock_domain_ticket = DomainTicket(
            id=django_ticket.id,
            title="Test",
            description="Desc",
            status=DomainTicket.OPEN,
            user_id="1",
            created_at=django_ticket.created_at,
            priority="High",
            priority_justification="Urgente"
        )
        mock_use_case.execute.return_value = mock_domain_ticket
        viewset.change_priority_use_case = mock_use_case

        request = self._make_drf_request(self.factory.patch('', {"priority": "High", "user_role": "Administrador"}))

        response = viewset.change_priority(request, pk=django_ticket.id)

        assert response.data['priority'] == "High"
        assert response.data.get('priority_justification') == "Urgente"


class TestTicketSerializer(TestCase):
    """Tests del TicketSerializer: validación de campos requeridos e integración de priority."""

    def test_serializer_accepts_valid_data(self):
        """Serializer acepta datos válidos."""
        data = {"title": "Test", "description": "Description", "user_id": "1"}
        serializer = TicketSerializer(data=data)

        assert serializer.is_valid()

    def test_serializer_rejects_missing_title(self):
        """Serializer rechaza datos sin título."""
        data = {"description": "Description"}
        serializer = TicketSerializer(data=data)

        assert not serializer.is_valid()
        assert 'title' in serializer.errors

    def test_serializer_rejects_missing_description(self):
        """Serializer rechaza datos sin descripción."""
        data = {"title": "Test"}
        serializer = TicketSerializer(data=data)

        assert not serializer.is_valid()
        assert 'description' in serializer.errors

    def test_serializer_rejects_title_too_long(self):
        """Serializer rechaza título demasiado largo."""
        data = {"title": "x" * 300, "description": "Desc"}
        serializer = TicketSerializer(data=data)

        assert not serializer.is_valid()
        assert 'title' in serializer.errors

    def test_serializer_includes_priority_in_response(self):
        """RED-4.1: Al serializar un ticket con priority, el campo aparece en los datos de salida."""
        ticket = DjangoTicket.objects.create(
            title="Test Priority",
            description="Descripción",
            priority="High",
        )
        serializer = TicketSerializer(instance=ticket)
        assert "priority" in serializer.data
        assert serializer.data["priority"] == "High"

    def test_serializer_includes_priority_justification_in_response(self):
        """RED-4.2: Al serializar un ticket con justificación, el campo aparece en la salida."""
        ticket = DjangoTicket.objects.create(
            title="Test Justification",
            description="Descripción",
            priority="High",
            priority_justification="Urgente",
        )
        serializer = TicketSerializer(instance=ticket)
        assert "priority_justification" in serializer.data
        assert serializer.data["priority_justification"] == "Urgente"

    def test_serializer_ignores_priority_on_creation(self):
        """RED-4.3: Al crear ticket vía POST, el campo priority en el body es ignorado."""
        data = {"title": "Test", "description": "Descripción", "priority": "High", "user_id": "1"}
        serializer = TicketSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert "priority" not in serializer.validated_data

    def test_serializer_ignores_priority_justification_on_creation(self):
        """RED-4.4: Al crear ticket vía POST, el campo priority_justification en el body es ignorado."""
        data = {"title": "Test", "description": "Descripción", "priority_justification": "Reason", "user_id": "1"}
        serializer = TicketSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert "priority_justification" not in serializer.validated_data


class TestTicketModel(TestCase):
    """Tests del modelo Django (persistencia)."""

    def test_ticket_model_creation_defaults_to_open(self):
        """Crear ticket sin status explícito usa OPEN por defecto."""
        ticket = DjangoTicket.objects.create(
            title="Test",
            description="Description"
        )

        assert ticket.status == "OPEN"
        assert ticket.created_at is not None

    def test_ticket_model_can_be_updated(self):
        """Modelo Django permite actualizaciones."""
        ticket = DjangoTicket.objects.create(
            title="Original",
            description="Original Desc",
            status="OPEN"
        )

        ticket.status = "IN_PROGRESS"
        ticket.save()

        ticket.refresh_from_db()
        assert ticket.status == "IN_PROGRESS"
```

#### `tickets/tests/integration/test_ticket_workflow.py`

```python
"""
Integration tests for complete ticket workflows.
Tests end-to-end scenarios with all architectural layers working together.

These tests validate:
- Clean Architecture layer interaction
- Domain-Driven Design patterns
- Repository pattern implementation
- Event-driven architecture
- Business rules enforcement across the stack
- Priority workflow validation
- Disabled generic CRUD methods (PUT/PATCH/DELETE return 405)
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import Mock, call, patch

from tickets.domain.entities import Ticket as DomainTicket
from tickets.domain.exceptions import (
    TicketAlreadyClosed,
    InvalidTicketStateTransition,
    InvalidTicketData,
    InvalidPriorityTransition,
    DomainException
)
from tickets.application.use_cases import (
    CreateTicketUseCase,
    CreateTicketCommand,
    ChangeTicketStatusUseCase,
    ChangeTicketStatusCommand,
    ChangeTicketPriorityUseCase,
    ChangeTicketPriorityCommand
)
from tickets.infrastructure.repository import DjangoTicketRepository
from tickets.infrastructure.event_publisher import RabbitMQEventPublisher
from tickets.models import Ticket as DjangoTicket


class TestCompleteTicketWorkflow(TestCase):
    """Integration tests for complete ticket workflows with all components."""

    def setUp(self):
        """Set up real repository and mock event publisher."""
        self.repository = DjangoTicketRepository()
        self.event_publisher = Mock(spec=RabbitMQEventPublisher)

    def tearDown(self):
        """Clean up database after each test."""
        DjangoTicket.objects.all().delete()

    # ==================== Happy Path Workflows ====================

    def test_complete_ticket_lifecycle(self):
        """Test: Complete ticket lifecycle from creation to closure."""
        # 1. Create ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )

        ticket = create_use_case.execute(
            CreateTicketCommand(
                title="Complete Lifecycle Test",
                description="Testing full workflow",
                user_id="1"
            )
        )

        # Verify initial state
        assert ticket.id is not None
        assert ticket.status == DomainTicket.OPEN
        assert self.event_publisher.publish.call_count == 1

        # Verify persistence
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.status == "OPEN"

        # 2. Move to IN_PROGRESS
        change_use_case = ChangeTicketStatusUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )

        ticket = change_use_case.execute(
            ChangeTicketStatusCommand(
                ticket_id=ticket.id,
                new_status=DomainTicket.IN_PROGRESS
            )
        )

        assert ticket.status == DomainTicket.IN_PROGRESS
        assert self.event_publisher.publish.call_count == 2

        db_ticket.refresh_from_db()
        assert db_ticket.status == "IN_PROGRESS"

        # 3. Close ticket
        ticket = change_use_case.execute(
            ChangeTicketStatusCommand(
                ticket_id=ticket.id,
                new_status=DomainTicket.CLOSED
            )
        )

        assert ticket.status == DomainTicket.CLOSED
        assert self.event_publisher.publish.call_count == 3

        db_ticket.refresh_from_db()
        assert db_ticket.status == "CLOSED"

    def test_direct_open_to_closed_transition(self):
        """Test: Ticket can go from OPEN to CLOSED via IN_PROGRESS."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Direct Close", "Test", "1")
        )

        # Close via IN_PROGRESS
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )
        ticket = change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.CLOSED)
        )

        # Verify
        assert ticket.status == DomainTicket.CLOSED
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.status == "CLOSED"

    def test_multiple_tickets_independent_workflows(self):
        """Test: Multiple tickets can have independent workflows."""
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )

        # Create three tickets
        ticket1 = create_use_case.execute(CreateTicketCommand("T1", "D1", "1"))
        ticket2 = create_use_case.execute(CreateTicketCommand("T2", "D2", "1"))
        ticket3 = create_use_case.execute(CreateTicketCommand("T3", "D3", "1"))

        # Move them to different states
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket1.id, DomainTicket.IN_PROGRESS)
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket2.id, DomainTicket.IN_PROGRESS)
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket2.id, DomainTicket.CLOSED)
        )
        # ticket3 stays OPEN

        # Verify independent states
        db_t1 = DjangoTicket.objects.get(pk=ticket1.id)
        db_t2 = DjangoTicket.objects.get(pk=ticket2.id)
        db_t3 = DjangoTicket.objects.get(pk=ticket3.id)

        assert db_t1.status == "IN_PROGRESS"
        assert db_t2.status == "CLOSED"
        assert db_t3.status == "OPEN"

    # ==================== Business Rules Enforcement ====================

    def test_cannot_modify_closed_ticket(self):
        """Test: Business rule - closed tickets cannot be modified."""
        # Create and close ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("To Close", "Test", "1")
        )

        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.CLOSED)
        )

        # Attempt to reopen
        with self.assertRaises(TicketAlreadyClosed):
            change_use_case.execute(
                ChangeTicketStatusCommand(ticket.id, DomainTicket.OPEN)
            )

        # Verify state unchanged
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.status == "CLOSED"

    def test_cannot_skip_to_invalid_status(self):
        """Test: Invalid state transitions are rejected."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Test", "Desc", "1")
        )

        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )

        # Try invalid transition
        with self.assertRaises(ValueError):
            change_use_case.execute(
                ChangeTicketStatusCommand(ticket.id, "INVALID_STATUS")
            )

    def test_idempotent_status_changes_do_not_publish_events(self):
        """Test: Changing to same status is idempotent and doesn't publish events."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Test", "Desc", "1")
        )

        initial_call_count = self.event_publisher.publish.call_count

        # Change to same status (OPEN -> OPEN)
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.OPEN)
        )

        # Verify no new event published
        assert self.event_publisher.publish.call_count == initial_call_count

        # Verify database unchanged
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.status == "OPEN"

    # ==================== Event Publishing Validation ====================

    def test_create_ticket_publishes_ticket_created_event(self):
        """Test: Creating ticket publishes TicketCreated event."""
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )

        ticket = create_use_case.execute(
            CreateTicketCommand("Event Test", "Testing events", "1")
        )

        # Verify event published
        assert self.event_publisher.publish.call_count == 1

        # Verify event type and data
        published_event = self.event_publisher.publish.call_args[0][0]
        assert published_event.__class__.__name__ == "TicketCreated"
        assert published_event.ticket_id == ticket.id
        assert published_event.title == "Event Test"
        assert published_event.description == "Testing events"
        assert published_event.status == "OPEN"

    def test_change_status_publishes_status_changed_event(self):
        """Test: Changing status publishes TicketStatusChanged event."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Test", "Desc", "1")
        )

        self.event_publisher.reset_mock()

        # Change status
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )

        # Verify event published
        assert self.event_publisher.publish.call_count == 1

        # Verify event data
        published_event = self.event_publisher.publish.call_args[0][0]
        assert published_event.__class__.__name__ == "TicketStatusChanged"
        assert published_event.ticket_id == ticket.id
        assert published_event.old_status == "OPEN"
        assert published_event.new_status == "IN_PROGRESS"

    def test_multiple_status_changes_publish_multiple_events(self):
        """Test: Each status change publishes a separate event."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Multi", "Events", "1")
        )

        # Track events
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )

        initial_count = self.event_publisher.publish.call_count

        # Make multiple changes
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.CLOSED)
        )

        # Verify two additional events published
        assert self.event_publisher.publish.call_count == initial_count + 2

    # ==================== Repository Pattern Validation ====================

    def test_repository_correctly_translates_domain_to_persistence(self):
        """Test: Repository correctly translates between domain and Django models."""
        # Create through use case
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        domain_ticket = create_use_case.execute(
            CreateTicketCommand("Translation Test", "Testing repository", "1")
        )

        # Verify domain entity properties
        assert isinstance(domain_ticket, DomainTicket)
        assert domain_ticket.status == DomainTicket.OPEN

        # Verify Django model properties
        django_ticket = DjangoTicket.objects.get(pk=domain_ticket.id)
        assert django_ticket.title == "Translation Test"
        assert django_ticket.description == "Testing repository"
        assert django_ticket.status == "OPEN"

        # Verify types match expected
        assert isinstance(django_ticket.title, str)
        assert isinstance(django_ticket.status, str)

    def test_repository_preserves_data_across_operations(self):
        """Test: Repository maintains data integrity across multiple operations."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Preserve", "Data integrity test", "1")
        )

        original_title = ticket.title
        original_description = ticket.description

        # Change status multiple times
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )

        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.CLOSED)
        )

        # Verify title and description unchanged
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.title == original_title
        assert db_ticket.description == original_description
        assert db_ticket.status == "CLOSED"

    # ==================== Error Handling ====================

    def test_invalid_ticket_data_raises_domain_exception(self):
        """Test: Invalid ticket data raises domain exception."""
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )

        # Try to create ticket with empty title
        with self.assertRaises(InvalidTicketData):
            create_use_case.execute(
                CreateTicketCommand(title="", description="No title", user_id="1")
            )

        # Verify no ticket created
        count = DjangoTicket.objects.count()
        assert count == 0

    def test_nonexistent_ticket_change_status_fails_gracefully(self):
        """Test: Attempting to change status of non-existent ticket raises ValueError."""
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )

        # Try to change status of non-existent ticket
        with self.assertRaises(ValueError):
            change_use_case.execute(
                ChangeTicketStatusCommand(
                    ticket_id=99999,
                    new_status=DomainTicket.CLOSED
                )
            )

    # ==================== Clean Architecture Validation ====================

    def test_use_case_depends_on_abstractions_not_implementations(self):
        """Test: Use cases depend on repository interface, not Django ORM."""
        # Create use case with repository
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )

        # Verify use case stores repository reference
        assert create_use_case.repository is self.repository
        assert create_use_case.event_publisher is self.event_publisher

        # Create ticket
        ticket = create_use_case.execute(
            CreateTicketCommand("Architecture", "Testing layers", "1")
        )

        # Verify domain entity returned (not Django model)
        assert isinstance(ticket, DomainTicket)
        assert not isinstance(ticket, DjangoTicket)

    def test_domain_entities_remain_independent_of_framework(self):
        """Test: Domain entities don't depend on Django or any framework."""
        # Create domain entity directly (no Django involved) using factory
        domain_ticket = DomainTicket.create(
            title="Pure Domain",
            description="No framework dependencies",
            user_id="1"
        )

        # Apply business rule
        domain_ticket.change_status(DomainTicket.IN_PROGRESS)

        # Verify entity behavior independent of persistence
        assert domain_ticket.status == DomainTicket.IN_PROGRESS

        # Now persist through repository
        saved_ticket = self.repository.save(domain_ticket)

        # Verify persistence successful
        assert saved_ticket.id is not None
        db_ticket = DjangoTicket.objects.get(pk=saved_ticket.id)
        assert db_ticket.status == "IN_PROGRESS"

    # ==================== Consistency Tests ====================

    def test_concurrent_status_changes_maintain_consistency(self):
        """Test: Multiple status changes maintain data consistency."""
        # Create ticket
        create_use_case = CreateTicketUseCase(
            self.repository,
            self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand("Concurrent", "Test", "1")
        )

        # Move to IN_PROGRESS first so both loads start from IN_PROGRESS
        change_use_case = ChangeTicketStatusUseCase(
            self.repository,
            self.event_publisher
        )
        change_use_case.execute(
            ChangeTicketStatusCommand(ticket.id, DomainTicket.IN_PROGRESS)
        )

        # Load ticket twice (simulating concurrent access)
        ticket1 = self.repository.find_by_id(ticket.id)
        ticket2 = self.repository.find_by_id(ticket.id)

        # Modify both and save
        ticket1.change_status(DomainTicket.CLOSED)
        self.repository.save(ticket1)

        ticket2.change_status(DomainTicket.CLOSED)
        self.repository.save(ticket2)

        # Verify last write wins
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.status == "CLOSED"

    def test_workflow_rollback_on_event_publish_failure(self):
        """Test: Workflow behavior when event publishing fails."""
        # Configure event publisher to raise exception
        failing_publisher = Mock(spec=RabbitMQEventPublisher)
        failing_publisher.publish.side_effect = Exception("RabbitMQ unavailable")

        create_use_case = CreateTicketUseCase(
            self.repository,
            failing_publisher
        )

        # Try to create ticket (should fail on event publish)
        with self.assertRaises(Exception):
            create_use_case.execute(
                CreateTicketCommand("Failing", "Event publish fails", "1")
            )

        # Note: Current implementation doesn't rollback on publish failure
        # This test documents current behavior
        # In production, consider implementing transaction boundaries

    # ==================== Priority Workflow Integration ====================

    def test_complete_priority_change_workflow(self):
        """RED-6.1: Flujo completo — crear ticket + cambiar prioridad persiste y publica evento."""
        # 1. Crear ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand(title="Priority Workflow", description="Integration test", user_id="1")
        )

        # 2. Cambiar prioridad
        change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        command = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command.user_role = "Administrador"
        command.justification = "Urgente"

        updated_ticket = change_priority_use_case.execute(command)

        # 3. Verificar entidad de dominio
        assert updated_ticket.priority == "High"
        assert updated_ticket.priority_justification == "Urgente"

        # 4. Verificar persistencia en BD
        db_ticket = DjangoTicket.objects.get(pk=ticket.id)
        assert db_ticket.priority == "High"
        assert db_ticket.priority_justification == "Urgente"

        # 5. Verificar evento TicketPriorityChanged publicado
        priority_events = [
            c for c in self.event_publisher.publish.call_args_list
            if c[0][0].__class__.__name__ == "TicketPriorityChanged"
        ]
        assert len(priority_events) == 1
        event = priority_events[0][0][0]
        assert event.ticket_id == ticket.id
        assert event.old_priority == "Unassigned"
        assert event.new_priority == "High"
        assert event.justification == "Urgente"

    def test_priority_change_on_closed_ticket_raises_error(self):
        """RED-6.2: Flujo — cambiar prioridad de ticket cerrado falla con TicketAlreadyClosed."""
        # 1. Crear ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand(title="Close Then Priority", description="Test", user_id="1")
        )

        # 2. Cerrar ticket: OPEN → IN_PROGRESS → CLOSED
        change_status_use_case = ChangeTicketStatusUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        change_status_use_case.execute(
            ChangeTicketStatusCommand(ticket_id=ticket.id, new_status=DomainTicket.IN_PROGRESS)
        )
        change_status_use_case.execute(
            ChangeTicketStatusCommand(ticket_id=ticket.id, new_status=DomainTicket.CLOSED)
        )

        # 3. Intentar cambiar prioridad en ticket cerrado
        change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        command = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command.user_role = "Administrador"

        with self.assertRaises(TicketAlreadyClosed):
            change_priority_use_case.execute(command)

    def test_priority_change_with_non_admin_raises_error(self):
        """RED-6.3: Flujo — cambiar prioridad con usuario no admin falla con DomainException."""
        # 1. Crear ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand(title="Non Admin Priority", description="Test", user_id="1")
        )

        # 2. Intentar cambiar prioridad con rol "Usuario"
        change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        command = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command.user_role = "Usuario"

        with self.assertRaises(DomainException) as ctx:
            change_priority_use_case.execute(command)

        assert "permiso insuficiente" in str(ctx.exception).lower()

    def test_revert_to_unassigned_raises_error_in_workflow(self):
        """RED-6.4: Flujo — reversión a Unassigned falla con InvalidPriorityTransition."""
        # 1. Crear ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand(title="Revert Priority", description="Test", user_id="1")
        )

        # 2. Asignar prioridad High
        change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        command_high = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command_high.user_role = "Administrador"
        change_priority_use_case.execute(command_high)

        # 3. Intentar revertir a Unassigned
        command_unassigned = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="Unassigned",
        )
        command_unassigned.user_role = "Administrador"

        with self.assertRaises(InvalidPriorityTransition):
            change_priority_use_case.execute(command_unassigned)

    def test_idempotent_priority_change_no_extra_event(self):
        """RED-6.5: Flujo — idempotencia: mismo valor no publica evento adicional."""
        # 1. Crear ticket
        create_use_case = CreateTicketUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        ticket = create_use_case.execute(
            CreateTicketCommand(title="Idempotent Priority", description="Test", user_id="1")
        )

        # 2. Cambiar prioridad a High (primera vez)
        change_priority_use_case = ChangeTicketPriorityUseCase(
            repository=self.repository,
            event_publisher=self.event_publisher
        )
        command = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command.user_role = "Administrador"
        change_priority_use_case.execute(command)

        # Registrar el conteo de llamadas después del primer cambio
        call_count_after_first = self.event_publisher.publish.call_count

        # 3. Cambiar prioridad a High (segunda vez — idempotente)
        command2 = ChangeTicketPriorityCommand(
            ticket_id=ticket.id,
            new_priority="High",
        )
        command2.user_role = "Administrador"
        change_priority_use_case.execute(command2)

        # Verificar que NO se publicó evento adicional
        assert self.event_publisher.publish.call_count == call_count_after_first

    # ==================== Disabled Generic CRUD Methods ====================

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
           return_value=None)
    def test_put_generic_returns_405_and_ticket_unchanged(self, mock_auth, mock_publish):
        """Gherkin AC-1: PUT /api/tickets/{id}/ returns 405 and ticket data stays intact."""
        # Create a ticket directly in DB for isolation
        ticket = DjangoTicket.objects.create(
            title="Original Title",
            description="Original Description",
            status="OPEN",
            user_id="user-1",
        )
        original_title = ticket.title
        original_description = ticket.description
        original_status = ticket.status

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/"
        response = client.put(url, {"title": "Hacked", "description": "Hacked"}, format="json")

        # Assert 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)

        # Assert ticket unchanged in DB
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, original_title)
        self.assertEqual(ticket.description, original_description)
        self.assertEqual(ticket.status, original_status)

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
           return_value=None)
    def test_patch_generic_returns_405_and_ticket_unchanged(self, mock_auth, mock_publish):
        """Gherkin AC-2: PATCH /api/tickets/{id}/ returns 405 and ticket data stays intact."""
        ticket = DjangoTicket.objects.create(
            title="Original Title",
            description="Original Description",
            status="OPEN",
            user_id="user-1",
        )
        original_title = ticket.title
        original_status = ticket.status

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/"
        response = client.patch(url, {"title": "Hacked"}, format="json")

        self.assertEqual(response.status_code, 405)

        ticket.refresh_from_db()
        self.assertEqual(ticket.title, original_title)
        self.assertEqual(ticket.status, original_status)

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate",
           return_value=None)
    def test_delete_generic_returns_405_and_ticket_intact(self, mock_auth, mock_publish):
        """Gherkin AC-3: DELETE /api/tickets/{id}/ returns 405 and ticket still exists."""
        ticket = DjangoTicket.objects.create(
            title="Should Not Be Deleted",
            description="Persistence check",
            status="OPEN",
            user_id="user-1",
        )

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/"
        response = client.delete(url)

        self.assertEqual(response.status_code, 405)

        # Ticket must still exist
        self.assertTrue(DjangoTicket.objects.filter(pk=ticket.id).exists())

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate")
    def test_custom_status_endpoint_still_works_after_refactor(self, mock_auth, mock_publish):
        """Gherkin AC-4: PATCH /api/tickets/{id}/status/ still works and publishes event."""
        # Simulate authenticated admin user
        mock_user = Mock()
        mock_user.token = {"role": "ADMIN"}
        mock_user.id = "admin-1"
        mock_user.is_authenticated = True
        mock_auth.return_value = (mock_user, "fake-token")

        ticket = DjangoTicket.objects.create(
            title="Status Endpoint Test",
            description="Integration check",
            status="OPEN",
            user_id="user-1",
        )

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/status/"
        response = client.patch(url, {"status": "IN_PROGRESS"}, format="json")

        self.assertEqual(response.status_code, 200)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "IN_PROGRESS")

        # Verify TicketStatusChanged event published
        status_events = [
            c for c in mock_publish.call_args_list
            if c[0][0].__class__.__name__ == "TicketStatusChanged"
        ]
        self.assertEqual(len(status_events), 1)

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate")
    def test_custom_priority_endpoint_still_works_after_refactor(self, mock_auth, mock_publish):
        """Gherkin AC-5: PATCH /api/tickets/{id}/priority/ still works and publishes event."""
        mock_user = Mock()
        mock_user.token = {"role": "ADMIN"}
        mock_user.id = "admin-1"
        mock_user.is_authenticated = True
        mock_auth.return_value = (mock_user, "fake-token")

        ticket = DjangoTicket.objects.create(
            title="Priority Endpoint Test",
            description="Integration check",
            status="OPEN",
            user_id="user-1",
        )

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/priority/"
        response = client.patch(
            url, {"priority": "High", "justification": "Urgente"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

        ticket.refresh_from_db()
        self.assertEqual(ticket.priority, "High")

        # Verify TicketPriorityChanged event published
        priority_events = [
            c for c in mock_publish.call_args_list
            if c[0][0].__class__.__name__ == "TicketPriorityChanged"
        ]
        self.assertEqual(len(priority_events), 1)

    @patch("tickets.infrastructure.event_publisher.RabbitMQEventPublisher.publish")
    @patch("tickets.infrastructure.cookie_auth.CookieJWTStatelessAuthentication.authenticate")
    def test_custom_responses_endpoint_still_works_after_refactor(self, mock_auth, mock_publish):
        """Gherkin AC-6: POST /api/tickets/{id}/responses/ still works and publishes event."""
        mock_user = Mock()
        mock_user.token = {"role": "ADMIN"}
        mock_user.id = "admin-1"
        mock_user.is_authenticated = True
        mock_auth.return_value = (mock_user, "fake-token")

        ticket = DjangoTicket.objects.create(
            title="Responses Endpoint Test",
            description="Integration check",
            status="OPEN",
            user_id="user-1",
        )

        client = APIClient()
        url = f"/api/tickets/{ticket.id}/responses/"
        response = client.post(
            url, {"text": "Resuelto", "admin_id": "admin-1"}, format="json"
        )

        self.assertEqual(response.status_code, 201)

        # Verify TicketResponseAdded event published
        response_events = [
            c for c in mock_publish.call_args_list
            if c[0][0].__class__.__name__ == "TicketResponseAdded"
        ]
        self.assertEqual(len(response_events), 1)
```

### Files Deleted

_None._

### Execution Steps

```bash
git add tickets/tests/unit/test_views.py tickets/tests/integration/test_ticket_workflow.py
git commit -m "test(views): verify disabled PUT/PATCH/DELETE and custom endpoint integrity"
```

---

## Final Verification

### Run the project

```bash
podman-compose up -d
```

### Run unit tests (domain only, pytest)

```bash
podman-compose exec backend pytest tickets/tests/unit/ -v
```

### Run integration tests (Django runner)

```bash
podman-compose exec backend python manage.py test tickets.tests.integration --verbosity=2
```

### Run all tests

```bash
podman-compose exec backend python manage.py test tickets --verbosity=2
```

### What should functionally work

1. **PUT `/api/tickets/{id}/`** → returns **405 Method Not Allowed**, ticket unchanged.
2. **PATCH `/api/tickets/{id}/`** → returns **405 Method Not Allowed**, ticket unchanged.
3. **DELETE `/api/tickets/{id}/`** → returns **405 Method Not Allowed**, ticket still exists.
4. **PATCH `/api/tickets/{id}/status/`** → returns **200**, status changes, `TicketStatusChanged` event published.
5. **PATCH `/api/tickets/{id}/priority/`** → returns **200**, priority changes, `TicketPriorityChanged` event published.
6. **POST `/api/tickets/{id}/responses/`** → returns **201**, response created, `TicketResponseAdded` event published.
7. **POST `/api/tickets/`** → still creates tickets via `CreateModelMixin` + `perform_create`.
8. **GET `/api/tickets/`** and **GET `/api/tickets/{id}/`** → still work via `ListModelMixin` and `RetrieveModelMixin`.

---

## Notes

- No new dependencies were introduced.
- No domain, application, or infrastructure layers were modified.
- The DRF `DefaultRouter` dynamically inspects viewset methods to determine which HTTP verbs to wire. Removing `UpdateModelMixin` and `DestroyModelMixin` means the router does not register PUT/PATCH/DELETE on the detail endpoint, resulting in 405 responses.
- The OpenAPI/Swagger schema (if configured) will automatically reflect the removal since DRF schema generation inspects available actions.
- Rollback is trivial: change the class declaration back to `viewsets.ModelViewSet` and remove the mixin imports.

---

## Design Review Summary

### SOLID Compliance

| Principle | Assessment |
|-----------|------------|
| **Single Responsibility (SRP)** | `TicketViewSet` continues to have a single responsibility: HTTP boundary. The change sharpens this by removing capabilities the controller should never fulfill (generic ORM-level update/delete). |
| **Open/Closed (OCP)** | Mixin composition is inherently OCP-friendly. The class is open for extension (add a new mixin or `@action` if a new legitimate endpoint is needed) but closed for modification — no existing behavior was altered. |
| **Liskov Substitution (LSP)** | Safe. We narrowed the interface by changing the base class from `ModelViewSet` to `GenericViewSet` + explicit mixins. No existing contracts are violated because the removed methods were never part of the intended API surface. |
| **Interface Segregation (ISP)** | This change **is** ISP in practice. `ModelViewSet` bundled `UpdateModelMixin` and `DestroyModelMixin` which the ViewSet should never implement. Explicit mixin composition exposes only the interfaces the class actually fulfills. |
| **Dependency Inversion (DIP)** | Unchanged. The ViewSet continues to depend on abstract use case interfaces and repository abstractions. The presentation layer has no direct ORM coupling for mutations. |

### GOF Patterns Applied

**None introduced.** The existing architecture already uses Command (use case DTOs), Repository (domain ↔ persistence), Factory (`TicketFactory.create()`), and Observer (domain events → RabbitMQ). This change is purely subtractive — removing inherited behavior via mixin composition — and does not warrant new patterns.

**Justification for not applying additional patterns:**
- **Strategy/State/Template Method:** Not applicable — we are removing capabilities, not adding conditional behavior.
- **Decorator:** Not applicable — we are not wrapping existing behavior, we are eliminating it.
- **Adapter:** Not applicable — no interface translation needed.
- **Chain of Responsibility:** Not applicable — no request forwarding chain involved.

DRF's mixin composition is the correct and sufficient mechanism for this architectural change.

### Clean Code Considerations

| Chapter Principle | How Respected |
|-------------------|---------------|
| **Meaningful names** | Class name `TicketViewSet` unchanged; mixin names are self-documenting (`CreateModelMixin`, `RetrieveModelMixin`, `ListModelMixin`). Test method names clearly describe what they verify. |
| **Small functions** | No new functions introduced. Existing functions untouched. |
| **One abstraction level** | The inheritance chain is now explicit and reads at a single abstraction level: "this ViewSet creates, retrieves, and lists." |
| **No comments explaining bad code** | The updated docstring explains the architectural *decision* (why mixins are excluded), not compensating for unclear code. |
| **No magic numbers** | HTTP status codes use DRF constants everywhere. |
| **No duplication** | Integration tests share a common pattern (create ticket → send request → assert) but each tests a distinct scenario. Factory helpers could reduce setup, but that would be over-engineering for 6 tests. |
| **Clear error handling** | All existing exception handlers preserved exactly. 405 responses are handled implicitly by DRF when the method is not found — no custom error handling needed. |
| **Testability by design** | Structural unit tests validate the class hierarchy (fast, no DB). Integration tests validate HTTP behavior end-to-end with mocked auth and event publisher. |
| **Functions do one thing** | Each test method verifies exactly one behavior or acceptance criterion. |
| **Separate concerns** | Tests are split: structural validation in unit tests, HTTP behavior in integration tests. |
| **Boy Scout Rule** | The docstring was improved to document the intentional exclusion of mixins for future maintainers. |

### Tradeoffs

1. **405 instead of 404 for PUT/PATCH/DELETE:** DRF returns 405 when a method is not allowed on an existing route. This is semantically correct (the resource exists, but the method is not supported) and is the standard REST behavior. An alternative would be to not register the detail route at all, but that would also remove GET on the detail endpoint.

2. **No runtime override fallback:** The plan chose mixin composition over `http_method_names` or method override with `405`. This is architecturally cleaner (the capability does not exist at all) but means a runtime hotfix to re-enable PUT/PATCH/DELETE would require a code change and redeployment. This was deemed acceptable given that these methods should never be enabled.

3. **Test authentication mocking:** Integration tests mock `CookieJWTStatelessAuthentication.authenticate` at the class level. This is a pragmatic tradeoff — testing the full JWT flow is out of scope for this feature. The mock returns a user object with the expected token structure, validating that the ViewSet correctly reads roles from the JWT.
