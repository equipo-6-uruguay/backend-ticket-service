# Análisis de Estructura — Backend Ticket Service

## 1. Visión General

**Tipo de proyecto:** Microservicio backend de gestión de tickets de soporte  
**Framework:** Django 6.0.2 + Django REST Framework  
**Lenguaje:** Python 3.12  
**Arquitectura:** Domain-Driven Design (DDD) + Event-Driven Architecture (EDA)  
**Base de datos:** PostgreSQL 16 (SQLite en memoria para tests)  
**Message Broker:** RabbitMQ (exchange fanout, durable)  
**Autenticación:** JWT stateless via HttpOnly cookie (`access_token`)  
**Contenedores:** Docker / podman-compose  

---

## 2. Estructura de Directorios

```
backend-ticket-service/
├── manage.py                          # Entry point de Django
├── conftest.py                        # Configuración pytest (SQLite in-memory)
├── Dockerfile                         # Python 3.12-slim, puerto 8000
├── docker-compose.yml                 # Stack completo (DB, backend, frontend, RabbitMQ)
├── check_deprecated_usage.py          # Utilidad para detectar uso deprecado
│
├── ticket_service/                    # Configuración del proyecto Django
│   ├── settings.py                    # Settings (PostgreSQL, JWT, CORS, seguridad)
│   ├── urls.py                        # URL raíz: /admin/ + /api/
│   ├── wsgi.py
│   └── asgi.py
│
└── tickets/                           # App principal (bounded context)
    ├── models.py                      # Modelos ORM (Ticket, TicketResponse)
    ├── serializer.py                  # Serializers DRF (validación XSS)
    ├── views.py                       # ViewSet (thin controller)
    ├── urls.py                        # Router DRF → /api/tickets/
    ├── admin.py                       # Registro Django Admin
    │
    ├── domain/                        # 🟢 Capa de Dominio (pura, sin framework)
    │   ├── entities.py                # Entidad Ticket (máquina de estados, reglas)
    │   ├── events.py                  # Eventos inmutables (frozen dataclasses)
    │   ├── exceptions.py              # Jerarquía de excepciones de dominio
    │   ├── factories.py               # TicketFactory (validación + creación)
    │   ├── repositories.py            # Interfaz abstracta TicketRepository
    │   └── event_publisher.py         # Interfaz abstracta EventPublisher
    │
    ├── application/                   # 🟡 Capa de Aplicación (orquestación)
    │   └── use_cases.py               # Commands + Use Cases (CQRS simplificado)
    │
    ├── infrastructure/                # 🔴 Capa de Infraestructura (adaptadores)
    │   ├── repository.py              # DjangoTicketRepository (ORM adapter)
    │   ├── event_publisher.py         # RabbitMQEventPublisher (mensajería)
    │   └── cookie_auth.py             # CookieJWTStatelessAuthentication
    │
    ├── migrations/                    # Migraciones de Django
    │
    └── tests/                         # Suite de pruebas
        ├── unit/                      # Tests unitarios (12 archivos)
        └── integration/               # Tests de integración (4 archivos)
```

---

## 3. Arquitectura por Capas

### 3.1 Capa de Dominio (`tickets/domain/`)

La capa más interna y protegida. **No tiene dependencias de framework**.

| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `entities.py` | 381 | Entidad `Ticket` con máquina de estados, validación de prioridad, gestión de respuestas y generación de eventos |
| `events.py` | 51 | 4 eventos inmutables: `TicketCreated`, `TicketStatusChanged`, `TicketPriorityChanged`, `TicketResponseAdded` |
| `exceptions.py` | 70 | 7 excepciones: `DomainException` → `TicketAlreadyClosed`, `InvalidTicketStateTransition`, `InvalidPriorityTransition`, `InvalidTicketData`, `DangerousInputError`, `EmptyResponseError`, `ResponseTooLongError` |
| `factories.py` | 82 | `TicketFactory.create()` con validación de campos vacíos y detección de HTML/XSS |
| `repositories.py` | 63 | Interfaz abstracta `TicketRepository` (4 métodos: `save`, `find_by_id`, `find_all`, `delete`) |
| `event_publisher.py` | 26 | Interfaz abstracta `EventPublisher` (método `publish`) |

**Patrones implementados:**
- **Entity Pattern:** `Ticket` como aggregate root con identidad y ciclo de vida
- **Factory Pattern:** Validación centralizada en la creación
- **Domain Events:** Eventos inmutables (`frozen=True`) generados por operaciones de dominio
- **Repository Pattern (puerto):** Abstracción para inversión de dependencias (DIP)
- **State Machine:** `OPEN` → `IN_PROGRESS` → `CLOSED` (transiciones estrictas, idempotentes)

**Reglas de negocio encapsuladas en la entidad:**
- Transición de estado: solo avance secuencial, nunca retroceso
- Ticket cerrado: inmutable (no acepta cambios de estado, prioridad ni respuestas)
- Prioridad: `Unassigned` → `Low`/`Medium`/`High` (no se puede volver a `Unassigned`)
- Justificación de prioridad: máximo 255 caracteres
- Respuesta: texto obligatorio, máximo 2000 caracteres
- Prevención XSS: regex `<[^>]+>` rechaza cualquier tag HTML

### 3.2 Capa de Aplicación (`tickets/application/`)

Orquesta operaciones de dominio sin contener reglas de negocio.

| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `use_cases.py` | 304 | 4 Commands + 4 Use Cases |

**Commands (DTOs de entrada):**
- `CreateTicketCommand(title, description, user_id)`
- `ChangeTicketStatusCommand(ticket_id, new_status)`
- `ChangeTicketPriorityCommand(ticket_id, new_priority)` + atributos dinámicos: `justification`, `user_role`
- `AddTicketResponseCommand(ticket_id, text, admin_id, response_id)`

**Use Cases (flujo estándar):**
1. Obtener entidad del repositorio (o crear via factory)
2. Ejecutar lógica de dominio en la entidad
3. Persistir cambios via repositorio
4. Recolectar y publicar eventos de dominio

**Patrones implementados:**
- **Command Pattern:** Objetos comando como DTOs inmutables
- **Use Case Pattern:** Una clase por operación de negocio
- **Dependency Injection:** Constructor recibe repositorio + event publisher

### 3.3 Capa de Infraestructura (`tickets/infrastructure/`)

Implementaciones concretas de los puertos definidos en el dominio.

| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `repository.py` | 153 | `DjangoTicketRepository`: traducción dominio ↔ ORM Django |
| `event_publisher.py` | 125 | `RabbitMQEventPublisher`: serialización JSON + fanout exchange |
| `cookie_auth.py` | 33 | `CookieJWTStatelessAuthentication`: JWT desde cookie HttpOnly |

**Patrones implementados:**
- **Adapter Pattern:** El repositorio traduce entre `Ticket` (dominio) y `Ticket` (ORM)
- **Anti-Corruption Layer:** `_to_domain()` / `to_django_model()` previenen fuga del ORM al dominio
- **Event Translation:** `_translate_event()` convierte eventos tipados a JSON serializable

### 3.4 Capa de Presentación (`tickets/views.py`, `serializer.py`, `urls.py`)

Thin controllers que delegan toda la lógica a los use cases.

| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `views.py` | 399 | `TicketViewSet` con 5 acciones (CRUD + status + priority + responses) |
| `serializer.py` | 107 | `TicketSerializer`, `TicketResponseSerializer` (validación XSS defensiva) |
| `urls.py` | 9 | Router DRF registrando `TicketViewSet` |

**Endpoints expuestos:**

| Método | Ruta | Acción |
|--------|------|--------|
| GET | `/api/tickets/` | Listar todos los tickets |
| POST | `/api/tickets/` | Crear ticket |
| GET | `/api/tickets/{id}/` | Obtener ticket por ID |
| PUT/PATCH | `/api/tickets/{id}/` | Actualizar ticket |
| DELETE | `/api/tickets/{id}/` | Eliminar ticket |
| PATCH | `/api/tickets/{id}/status/` | Cambiar estado |
| PATCH | `/api/tickets/{id}/priority/` | Cambiar prioridad |
| GET | `/api/tickets/{id}/responses/` | Listar respuestas |
| POST | `/api/tickets/{id}/responses/` | Agregar respuesta (solo ADMIN) |
| GET | `/api/tickets/my-tickets/{user_id}/` | Tickets de un usuario |

---

## 4. Modelos de Persistencia (ORM)

### `Ticket` (modelo Django)
| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `id` | AutoField (PK) | Auto-generado |
| `title` | CharField(255) | Requerido |
| `description` | TextField | Requerido |
| `status` | CharField(20) | Choices: OPEN, IN_PROGRESS, CLOSED. Default: OPEN |
| `user_id` | CharField(255) | Referencia lógica (NO FK) — desacoplamiento microservicios |
| `created_at` | DateTimeField | auto_now_add |
| `priority` | CharField(20) | Choices: Unassigned, Low, Medium, High. Default: Unassigned |
| `priority_justification` | TextField | Nullable, blank |

### `TicketResponse` (modelo Django)
| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `id` | AutoField (PK) | Auto-generado |
| `ticket` | ForeignKey(Ticket) | CASCADE, related_name="responses" |
| `admin_id` | CharField(255) | ID del admin que responde |
| `text` | TextField(2000) | Texto de la respuesta |
| `created_at` | DateTimeField | auto_now_add |

> **Decisión de diseño clave:** `user_id` es `CharField`, no `ForeignKey`. Esto permite que el servicio de tickets y el servicio de usuarios tengan bases de datos independientes (loose coupling entre microservicios).

---

## 5. Flujo de Eventos (EDA)

```
┌──────────────┐     ┌──────────────┐     ┌───────────────────┐     ┌──────────┐
│  ViewSet     │────▶│  Use Case    │────▶│  Domain Entity    │────▶│  Events  │
│  (HTTP in)   │     │  (orchestr.) │     │  (business logic) │     │  (list)  │
└──────────────┘     └──────┬───────┘     └───────────────────┘     └────┬─────┘
                            │                                            │
                            │  collect_domain_events()                   │
                            │◀───────────────────────────────────────────┘
                            │
                            ▼
                     ┌──────────────────┐     ┌──────────────┐
                     │ EventPublisher   │────▶│  RabbitMQ    │
                     │ (publish each)   │     │  (fanout)    │
                     └──────────────────┘     └──────────────┘
```

**Eventos publicados:**
| Evento | Trigger | Datos clave |
|--------|---------|-------------|
| `ticket.created` | `CreateTicketUseCase` | ticket_id, title, description, status |
| `ticket.status_changed` | `ChangeTicketStatusUseCase` | ticket_id, old_status, new_status |
| `ticket.priority_changed` | `ChangeTicketPriorityUseCase` | ticket_id, old/new priority, justification |
| `ticket.response_added` | `AddTicketResponseUseCase` | ticket_id, response_id, admin_id, text, user_id |

---

## 6. Seguridad

### Autenticación
- **JWT Stateless** via `rest_framework_simplejwt`
- Token leído primero desde cookie HttpOnly `access_token`, fallback a header `Authorization: Bearer`
- Sin tabla de usuarios local (stateless para microservicios consumer)

### Autorización
- Solo usuarios con rol `ADMIN` pueden: crear respuestas, cambiar prioridad
- Listado de respuestas restringido al creador del ticket o ADMIN
- Rol extraído del JWT claim `role`

### Prevención XSS (defensa en profundidad)
1. **Capa serializer:** `validate_title()` / `validate_description()` con `_contains_dangerous_html()`
2. **Capa factory:** `TicketFactory.create()` valida contra HTML antes de crear la entidad
3. **Regex:** `<[^>]+>` rechaza cualquier tag HTML

### Hardening (producción)
- `SECURE_BROWSER_XSS_FILTER`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = "DENY"`
- Cookies seguras: `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`
- Browsable API deshabilitada en producción

---

## 7. Métricas del Código

### Código de producción
| Capa | Archivos | Líneas |
|------|----------|--------|
| Dominio | 6 | 673 |
| Aplicación | 1 | 304 |
| Infraestructura | 3 | 311 |
| Presentación | 3 | 515 |
| Configuración | 4 | 254 |
| Utilidades | 2 | 238 |
| **Total producción** | **19** | **~2,295** |

### Código de tests
| Tipo | Archivos | Líneas |
|------|----------|--------|
| Unitarios | 12 | 3,945 |
| Integración | 4 | 1,595 |
| **Total tests** | **16** | **5,539** |

**Ratio test/producción: ~2.4:1** — Buena cobertura de pruebas.

---

## 8. Principios y Patrones Identificados

| Principio / Patrón | Dónde se aplica |
|---------------------|-----------------|
| **DDD (Domain-Driven Design)** | Separación dominio / aplicación / infraestructura |
| **EDA (Event-Driven Architecture)** | Eventos de dominio → RabbitMQ fanout |
| **CQRS (simplificado)** | Commands como DTOs de entrada para use cases |
| **Hexagonal Architecture (Ports & Adapters)** | Interfaces en dominio, implementaciones en infra |
| **Dependency Inversion (DIP)** | Use cases dependen de abstracciones, no implementaciones concretas |
| **Factory Pattern** | `TicketFactory` centraliza validación y creación |
| **Repository Pattern** | Abstracción de persistencia, traducción dominio ↔ ORM |
| **State Machine** | Transiciones estrictas OPEN → IN_PROGRESS → CLOSED |
| **Command Pattern** | Dataclasses inmutables como objetos de comando |
| **Anti-Corruption Layer** | Métodos `_to_domain()` / `to_django_model()` en el repositorio |
| **Defense in Depth (XSS)** | Validación en serializer + factory + modelo |
| **Loose Coupling** | `user_id` como CharField (sin FK entre microservicios) |

---

## 9. Dependencias Externas Clave

| Dependencia | Uso |
|-------------|-----|
| `Django 6.0.2` | Framework web |
| `djangorestframework` | API REST |
| `djangorestframework-simplejwt` | Autenticación JWT stateless |
| `django-cors-headers` | CORS para frontend SPA |
| `pika` | Cliente RabbitMQ (AMQP) |
| `python-dotenv` | Variables de entorno desde `.env` |
| `psycopg2` (implícito) | Driver PostgreSQL |
| `pytest` / `pytest-django` | Test runner para pruebas unitarias |

---
