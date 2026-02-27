# Dolores vs. Clean Architecture — Análisis Comparativo

Documento que contrasta cada problema identificado en `DOLORES.md` con los beneficios concretos que aportaría una migración hacia **Clean Architecture** (Uncle Bob / Robert C. Martin).

---

## Principios clave de Clean Architecture

Antes de contrastar, recordemos las reglas fundamentales:

1. **Dependency Rule**: Las dependencias apuntan siempre hacia adentro (Entities ← Use Cases ← Interface Adapters ← Frameworks).
2. **Entities**: Encapsulan reglas de negocio críticas, independientes de cualquier framework.
3. **Use Cases**: Orquestan flujo de datos hacia/desde entidades; contienen reglas de aplicación.
4. **Interface Adapters**: Convierten datos entre el formato de use cases/entities y el formato externo (DB, HTTP, mensajería).
5. **Frameworks & Drivers**: La capa más externa — Django, RabbitMQ, PostgreSQL son detalles de implementación enchufables.

---

## 1. Violaciones a la Arquitectura DDD

### Dolor 1.1 — ViewSet accede directamente al ORM

| Situación Actual | Con Clean Architecture |
|---|---|
| `my_tickets()`, `_list_responses()` y `_create_response()` ejecutan queries ORM (`Ticket.objects.filter`, `TicketResponse.objects.create`) directamente desde el controlador. | La **Dependency Rule** lo prohíbe: la capa de presentación (Frameworks) **jamás** conoce la capa de persistencia. Toda interacción pasa obligatoriamente por un **Use Case** que consume un **puerto** (interfaz de repositorio). |

**Beneficio concreto:** Al definir puertos como `ListUserTicketsUseCase` y `ListTicketResponsesUseCase`, el ViewSet queda reducido a un adaptador HTTP puro. Se puede reemplazar Django por FastAPI o Flask sin tocar una sola línea de lógica de negocio.

---

### Dolor 1.2 — `TicketResponse` sin entidad de dominio

| Situación Actual | Con Clean Architecture |
|---|---|
| `TicketResponse` existe solo como modelo ORM. Se crea y consulta sin representación en el dominio. Validación dispersa. | Cada concepto de negocio que tiene reglas propias **debe** ser una entidad o value object en la capa Entities. Clean Architecture exige que las reglas de negocio estén en el centro del sistema, no dispersas en adaptadores. |

**Beneficio concreto:** Crear `TicketResponse` como entidad de dominio centraliza validación (longitud, XSS, relación con ticket), habilita testing unitario puro y elimina la dependencia de Django ORM para verificar reglas de negocio.

---

### Dolor 1.3 — `ModelViewSet` expone CRUD basado en ORM

| Situación Actual | Con Clean Architecture |
|---|---|
| El ViewSet hereda `ModelViewSet` con `queryset = Ticket.objects.all()`, exponiendo operaciones CRUD automáticas que bypasean el dominio. | Los controladores en Clean Architecture son **adaptadores delgados** que solo traducen HTTP → Command/Query → Use Case → Response. No conocen el ORM ni tienen acceso a querysets. |

**Beneficio concreto:** Reemplazar `ModelViewSet` por `ViewSet` (o `APIView`) elimina la dualidad DDD/CRUD. Cada endpoint invoca explícitamente un use case, garantizando que **todo** flujo pase por las reglas de negocio. La superficie de API es intencional, nunca accidental.

---

## 2. Problemas en la Capa de Dominio

### Dolor 2.1 — `add_response()` no genera evento de dominio

| Situación Actual | Con Clean Architecture |
|---|---|
| `change_status()` y `change_priority()` generan eventos dentro de la entidad, pero `add_response()` delega esta responsabilidad al use case. Dos patrones coexisten. | En Clean Architecture, las **entidades encapsulan toda la lógica de negocio**, incluyendo la generación de eventos de dominio. Los use cases orquestan, no generan. Un solo patrón consistente. |

**Beneficio concreto:** Unificar la generación de eventos en la entidad `Ticket` garantiza consistencia. Cualquier camino de código que invoque `add_response()` — sea desde un use case, un job en background o un test — producirá el evento correspondiente sin depender de que el llamador "recuerde" crearlo.

---

### Dolor 2.2 — `TicketCreated` no se genera desde la entidad

| Situación Actual | Con Clean Architecture |
|---|---|
| El evento se construye manualmente en el use case porque se necesita el ID de base de datos. La generación de eventos está acoplada a una limitación de infraestructura. | Clean Architecture resuelve esto con **IDs generados en el dominio** (UUID) en lugar de IDs auto-incrementales de la BD. La entidad genera el evento en el momento de creación, con su propio ID. La BD simplemente persiste lo que el dominio decide. |

**Beneficio concreto:** Usar UUIDs generados por la factory/entidad elimina la dependencia circular "necesito persistir para tener ID, necesito ID para crear evento". El flujo se vuelve: Factory crea entidad con UUID → entidad genera `TicketCreated` → repositorio persiste → publisher emite eventos. Secuencial, limpio, testeable.

---

### Dolor 2.3 — Constantes duplicadas entre dominio y ORM

| Situación Actual | Con Clean Architecture |
|---|---|
| `OPEN`, `IN_PROGRESS`, `CLOSED` definidos tanto en la entidad de dominio como en el modelo ORM. Sin single source of truth. | La **Dependency Rule** establece que el dominio es el origen de verdad. La capa de infraestructura (ORM) **importa** las constantes del dominio, nunca al revés. |

**Beneficio concreto:** Definir un `TicketStatus` enum en la capa de dominio y que el modelo ORM lo referencie elimina la duplicación. Un cambio en un solo lugar se propaga automáticamente. Esto previene bugs silenciosos por inconsistencia de valores.

---

### Dolor 2.4 — `datetime.now()` hardcodeado

| Situación Actual | Con Clean Architecture |
|---|---|
| Las entidades llaman a `datetime.now()` directamente, imposibilitando tests deterministas. | Clean Architecture promueve la **inyección de dependencias** incluso para servicios de infraestructura como el reloj. Se define un puerto `Clock` (interfaz) que la entidad o factory recibe. |

**Beneficio concreto:** Inyectar un `Clock` (o pasar `now` como parámetro a la factory) permite tests deterministas, reproducibilidad total y la capacidad de simular escenarios temporales (expiración, SLAs) sin hacks como `freezegun`.

---

### Dolor 2.5 — Sin validación XSS en `add_response()`

| Situación Actual | Con Clean Architecture |
|---|---|
| La factory valida HTML en `title`/`description`, pero `add_response()` no aplica la misma protección. | En Clean Architecture, la validación de integridad de datos es responsabilidad de las entidades y value objects. Un `ResponseText` value object encapsularía la validación de XSS de forma reutilizable. |

**Beneficio concreto:** Crear un value object `SanitizedText` que valide contra XSS una sola vez y se reutilice en `title`, `description` y `response_text` unifica la protección. Imposible olvidar la validación en un campo nuevo: el tipo lo garantiza en compilación/instanciación.

---

## 3. Problemas en la Capa de Aplicación

### Dolor 3.1 — `ChangeTicketPriorityCommand` con campos dinámicos vía `getattr`

| Situación Actual | Con Clean Architecture |
|---|---|
| El command es un dataclass incompleto; `justification` y `user_role` se asignan dinámicamente, rompiendo la inmutabilidad. | Los **Commands** en Clean Architecture son DTOs inmutables con todos sus campos explícitos. Son contratos claros entre la capa de presentación y los use cases. |

**Beneficio concreto:** Definir `ChangeTicketPriorityCommand(ticket_id, new_priority, justification, user_role)` explícitamente hace que el contrato sea evidente, facilita el autocompletado del IDE, previene typos en nombres de atributos y permite validación estática con mypy/pyright.

---

### Dolor 3.2 — Lógica de autorización en el use case

| Situación Actual | Con Clean Architecture |
|---|---|
| La verificación de permisos ("solo ADMIN puede cambiar prioridad") está dispersa entre el ViewSet y el use case. | Clean Architecture separa **autorización** como un *cross-cutting concern* que se resuelve en la capa de Interface Adapters (middleware, decoradores, guardias) **antes** de que el request llegue al use case. |

**Beneficio concreto:** Extraer la autorización a un middleware o decorador (`@require_role("ADMIN")`) permite que los use cases se enfoquen exclusivamente en reglas de negocio. La autorización se testea de forma aislada y se reutiliza entre endpoints sin duplicación.

---

### Dolor 3.3 — Mapeo de roles hardcodeado

| Situación Actual | Con Clean Architecture |
|---|---|
| `"ADMIN"` del JWT se traduce a `"Administrador"` con un `if` hardcodeado en el ViewSet. | En Clean Architecture, la traducción entre representaciones externas e internas ocurre en la capa de **Interface Adapters**. Un `RoleMapper` o value object `Role` centraliza esta conversión. |

**Beneficio concreto:** Un `RoleMapper` centralizado (o un enum `Role` con método `from_jwt_claim()`) elimina las magic strings dispersas, facilita agregar nuevos roles y asegura que la traducción ocurra en un único punto controlado.

---

## 4. Problemas de Infraestructura

### Dolor 4.1 — Conexión nueva a RabbitMQ por cada evento

| Situación Actual | Con Clean Architecture |
|---|---|
| Cada `publish()` abre y cierra una conexión TCP. Sin pooling. | En Clean Architecture, los detalles de conexión son responsabilidad exclusiva de la capa Frameworks & Drivers. La interfaz `EventPublisher` del dominio no sabe ni le importa si hay pooling. |

**Beneficio concreto:** Al tener la interfaz `EventPublisher` desacoplada, se puede reemplazar la implementación por una con connection pooling, o incluso por un publisher in-memory para tests, sin modificar ninguna otra capa. La mejora de rendimiento es un cambio de infraestructura puro.

---

### Dolor 4.2 — Sin resiliencia en publicación de eventos

| Situación Actual | Con Clean Architecture |
|---|---|
| Sin retry, circuit breaker, outbox pattern ni dead letter queue. Si RabbitMQ falla tras la persistencia, el evento se pierde. | Clean Architecture facilita la implementación del **Outbox Pattern**: los eventos se persisten en la misma transacción que la entidad (mismo boundary transaccional). Un proceso aparte los publica y gestiona reintentos. |

**Beneficio concreto:** Al separar claramente persistencia (repositorio) de publicación (publisher), se puede introducir un `OutboxRepository` que guarde eventos en una tabla de la misma BD dentro de la transacción del `save()`. Un worker posterior los publica con retry y dead letter handling. Consistencia eventual garantizada, cero pérdida de eventos.

---

### Dolor 4.3 — `to_django_model()` ejecuta query adicional

| Situación Actual | Con Clean Architecture |
|---|---|
| El repositorio convierte dominio → ORM ejecutando un `SELECT` adicional para obtener el modelo Django. | En Clean Architecture, la serialización HTTP no pasa por el ORM. El use case retorna un **Output DTO** (no una entidad) que el controlador convierte directamente a JSON. |

**Beneficio concreto:** Introducir Output DTOs (o Response Models) elimina el query extra. El flujo es: Use Case → Output DTO → Serializer HTTP. El ORM solo participa en lectura/escritura de repositorio, nunca en serialización de respuestas. Menos queries, menos latencia.

---

### Dolor 4.4 — `print()` como logging

| Situación Actual | Con Clean Architecture |
|---|---|
| `print()` hardcodeado en el publisher. Sin framework de logging. | La capa de infraestructura en Clean Architecture utiliza servicios configurables. El logging es una dependencia inyectable a través de un puerto. |

**Beneficio concreto:** Reemplazar `print()` por `logging.getLogger(__name__)` y configurar logging en settings permite control de niveles (DEBUG/INFO/WARNING), rotación de archivos, integración con servicios de observabilidad (ELK, Datadog) y filtrado por módulo. Cambio mínimo, impacto máximo en operabilidad.

---

## 5. Problemas en la Capa de Presentación

### Dolor 5.1 — Manejo de excepciones repetitivo

| Situación Actual | Con Clean Architecture |
|---|---|
| Cada action tiene su propio `try/except` con la misma cadena de excepciones de dominio. | Clean Architecture promueve un **Exception Handler centralizado** en la capa de Interface Adapters. DRF lo soporta nativamente con `EXCEPTION_HANDLER` en settings. |

**Beneficio concreto:** Un `custom_exception_handler` que mapee `DomainException → 400`, `TicketAlreadyClosed → 409`, `TicketNotFound → 404` elimina toda duplicación. Los ViewSets quedan limpios de try/except, y la consistencia de códigos HTTP está garantizada por diseño.

```python
# Ejemplo: config centralizada en un punto
DOMAIN_EXCEPTION_MAP = {
    TicketAlreadyClosed: (status.HTTP_409_CONFLICT, "Ticket cerrado"),
    InvalidTicketStateTransition: (status.HTTP_400_BAD_REQUEST, "Transición inválida"),
    TicketNotFound: (status.HTTP_404_NOT_FOUND, "Ticket no encontrado"),
}
```

---

### Dolor 5.2 — `my_tickets()` sin paginación

| Situación Actual | Con Clean Architecture |
|---|---|
| Retorna todos los tickets sin límite. | En Clean Architecture, los **use cases de lectura** (queries) aceptan parámetros de paginación como parte del Input DTO. El repositorio implementa paginación a nivel de query. |

**Beneficio concreto:** Un `ListUserTicketsQuery(user_id, page, page_size)` permite que el repositorio aplique `LIMIT/OFFSET` (o cursor) y que el use case retorne metadatos de paginación. La paginación se vuelve un requisito explícito del contrato, no un afterthought.

---

### Dolor 5.3 — `fields = "__all__"` en el serializer

| Situación Actual | Con Clean Architecture |
|---|---|
| El serializer expone todos los campos del modelo ORM automáticamente. | En Clean Architecture, los serializers trabajan con **Output DTOs**, no con modelos ORM. Los campos expuestos son una decisión explícita de la capa de presentación. |

**Beneficio concreto:** Los Output DTOs actúan como barrera entre el modelo interno y la API pública. Agregar un campo al modelo ORM no lo expone automáticamente en la API. Los contratos de API son deliberados e inmutables salvo decisión explícita.

---

### Dolor 5.4 — Falta de autorización en `my_tickets()` (IDOR)

| Situación Actual | Con Clean Architecture |
|---|---|
| Cualquier usuario autenticado puede listar tickets de otro usuario. No se valida que `user_id` del path coincida con el usuario autenticado. | En Clean Architecture, la autorización se implementa como un **adaptador de interfaz** (middleware/guard) que verifica ownership antes de invocar el use case. |

**Beneficio concreto:** Un guard `OwnershipValidator` compara `request.user.id` con `path.user_id` antes de llegar al use case. Esto cierra la vulnerabilidad IDOR de raíz y aplica el principio de **least privilege** de forma reutilizable.

---

## 6. Problemas en la Suite de Tests

### Dolor 6.1 — Archivos de test con nombres ambiguos

| Situación Actual | Con Clean Architecture |
|---|---|
| Tests duplicados o con nombres confusos (`test_integration.py` en `unit/`). | Clean Architecture organiza tests por capa: `tests/domain/` (puro, sin mocks), `tests/application/` (use cases con mocks de puertos), `tests/infrastructure/` (integración real), `tests/presentation/` (HTTP). |

**Beneficio concreto:** La estructura de tests refleja la arquitectura. Es obvio dónde va cada test, qué dependencias necesita y qué alcance tiene. Elimina ambigüedad y solapamiento.

```
tests/
├── domain/          # Entidades, factories, value objects (sin mocks)
├── application/     # Use cases (mocks de repos/publishers)
├── infrastructure/  # Repositorios, publishers (BD y broker reales)
└── presentation/    # Endpoints HTTP (integración completa)
```

---

### Dolor 6.2 — Doble runner (pytest + Django test runner)

| Situación Actual | Con Clean Architecture |
|---|---|
| Dos runners con configuraciones distintas de BD. | Con capas bien separadas, **pytest puro** puede ejecutar tests de dominio y aplicación sin Django. Solo la capa de infraestructura/presentación necesita el runner de Django (vía `pytest-django`). |

**Beneficio concreto:** Un único runner (`pytest` con plugin `pytest-django`) unifica ejecución, reporte y configuración. Los tests de dominio ni siquiera necesitan la BD, ejecutándose en milisegundos.

---

### Dolor 6.3 — Sin cobertura de código

| Situación Actual | Con Clean Architecture |
|---|---|
| No hay métricas de cobertura configuradas. | Clean Architecture hace natural definir umbrales de cobertura por capa: dominio 95%+, aplicación 90%+, infraestructura 80%+. |

**Beneficio concreto:** Configurar `pytest-cov` con separación por capa permite medir y enforcar cobertura donde más importa (dominio). Un `pyproject.toml` con `[tool.coverage.run]` y CI que falle bajo cierto umbral cierra el ciclo.

---

## 7. Problemas de Configuración y DevOps

### Dolor 7.1 — Sin health check para el backend

| Situación Actual | Con Clean Architecture |
|---|---|
| El servicio no expone endpoint de health ni readiness. | Clean Architecture implementa health checks como un use case trivial (`HealthCheckUseCase`) que valida conectividad a dependencias (BD, RabbitMQ). |

**Beneficio concreto:** Un `/health` endpoint que invoque `HealthCheckUseCase` permite a Docker, Kubernetes y load balancers verificar el estado del servicio. Se testea como cualquier otro use case.

---

### Dolor 7.2 — `runserver` en Docker

| Situación Actual | Con Clean Architecture |
|---|---|
| Se usa el servidor de desarrollo de Django en el compose. | La separación entre framework y aplicación hace natural usar servidores WSGI/ASGI de producción (gunicorn, uvicorn). Django es un detalle reemplazable. |

**Beneficio concreto:** Migrar a `gunicorn --workers 4 --bind 0.0.0.0:8000 ticket_service.wsgi` da concurrencia real, manejo de workers y estabilidad de producción. Un cambio de una línea en el Dockerfile.

---

## 8. Deuda Técnica General

### Dolor 8.1 — No hay `TicketResponseRepository`

| Situación Actual | Con Clean Architecture |
|---|---|
| CRUD de `TicketResponse` vía ORM directamente. | Si `TicketResponse` es una entidad, necesita su propio **puerto de repositorio**. Si es un value object parte de `Ticket`, se persiste a través del `TicketRepository`. |

**Beneficio concreto:** Consistencia arquitectónica. Cada aggregate root tiene su repositorio. Las respuestas se gestionan a través de su aggregate (`Ticket`) o su propio repositorio, nunca directamente desde un controlador.

---

### Dolor 8.5 — Magic strings dispersas

| Situación Actual | Con Clean Architecture |
|---|---|
| `"ADMIN"`, `"Administrador"`, `"access_token"` hardcodeados en múltiples archivos. | Clean Architecture centraliza constantes en la capa de dominio (enums, value objects) y de configuración. Las capas externas importan, nunca redefinen. |

**Beneficio concreto:** Un enum `Role` con `ADMIN = "ADMIN"` y un método `display_name()` elimina strings mágicas. Cambiar el nombre de un rol requiere modificar un solo archivo. Refactoring seguro con soporte del IDE.

---

## 9. Especificación de Endpoints API

### Base URL

```
http://localhost:8000/api/v1
```

### Autenticación

Todos los endpoints requieren autenticación JWT mediante cookie HttpOnly `access_token`.

---

### 📋 Tickets: Listar

#### GET /tickets/

**Descripción:** Lista todos los tickets con paginación.

**Query Parameters:**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|----------|-------------|
| `page` | integer | No | Número de página (default: 1) |
| `page_size` | integer | No | Elementos por página (default: 20, max: 100) |
| `user_id` | string | No | Filtrar tickets por usuario |
| `status` | string | No | Filtrar por estado: `OPEN`, `IN_PROGRESS`, `CLOSED` |
| `priority` | string | No | Filtrar por prioridad: `Low`, `Medium`, `High` |

**Response 200 OK:**

```json
{
  "count": 150,
  "next": "http://localhost:8000/api/v1/tickets/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "title": "Bug crítico",
      "description": "Sistema no inicia",
      "status": "OPEN",
      "priority": "High",
      "user_id": "user1",
      "created_at": "2026-02-25T10:30:00Z",
      "updated_at": "2026-02-25T10:30:00Z"
    }
  ]
}
```

**Response 401 Unauthorized:** Falta token o token inválido.

---

### 🆕 Tickets: Crear

#### POST /tickets/

**Descripción:** Crea un nuevo ticket.

**Request Body:**

```json
{
  "title": "Bug crítico",
  "description": "Sistema no inicia en producción",
  "user_id": "user1"
}
```

**Validación:**

- `title`: requerido, string, max 255 caracteres, sin HTML tags
- `description`: requerido, string, max 2000 caracteres, sin HTML tags
- `user_id`: requerido, string, max 100 caracteres

**Response 201 Created:**

```json
{
  "id": 42,
  "title": "Bug crítico",
  "description": "Sistema no inicia en producción",
  "status": "OPEN",
  "priority": "Unassigned",
  "priority_justification": null,
  "user_id": "user1",
  "created_at": "2026-02-25T10:35:00Z",
  "updated_at": "2026-02-25T10:35:00Z"
}
```

**Response 400 Bad Request:**

```json
{
  "error": "Mensaje descriptivo del error de validación"
}
```

**Eventos Publicados:** `TicketCreated`

---

### 📖 Tickets: Obtener

#### GET /tickets/{id}/

**Descripción:** Obtiene detalles de un ticket específico.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `id` | integer | ID del ticket |

**Response 200 OK:**

```json
{
  "id": 1,
  "title": "Bug crítico",
  "description": "Sistema no inicia",
  "status": "IN_PROGRESS",
  "priority": "High",
  "priority_justification": "Cliente VIP",
  "user_id": "user1",
  "created_at": "2026-02-24T14:00:00Z",
  "updated_at": "2026-02-25T10:00:00Z",
  "responses": [
    {
      "id": 10,
      "text": "Equipo investigando",
      "admin_id": "admin1",
      "created_at": "2026-02-25T09:00:00Z"
    }
  ]
}
```

**Response 404 Not Found:** Ticket no existe.

```json
{
  "error": "Ticket 999 no encontrado"
}
```

---

### 🔄 Tickets: Cambiar Estado

#### PATCH /tickets/{id}/status/

**Descripción:** Cambia el estado del ticket.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `id` | integer | ID del ticket |

**Request Body:**

```json
{
  "status": "IN_PROGRESS"
}
```

**Estados Válidos:** `OPEN`, `IN_PROGRESS`, `CLOSED`

**Transiciones Permitidas:**
- `OPEN` → `IN_PROGRESS`
- `OPEN` → `CLOSED`
- `IN_PROGRESS` → `CLOSED`

**Response 200 OK:**

```json
{
  "id": 1,
  "status": "IN_PROGRESS",
  "updated_at": "2026-02-25T10:40:00Z"
}
```

**Response 400 Bad Request:**

```json
{
  "error": "No se puede cambiar ticket CLOSED a OPEN"
}
```

**Response 404 Not Found:** Ticket no existe.

**Eventos Publicados:** `TicketStatusChanged`

---

### 🎯 Tickets: Cambiar Prioridad

#### PATCH /tickets/{id}/priority/

**Descripción:** Cambia la prioridad del ticket (solo ADMIN).

**Autorización:** Requiere rol `ADMIN`

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `id` | integer | ID del ticket |

**Request Body:**

```json
{
  "priority": "High",
  "priority_justification": "Cliente VIP solicitó escalada"
}
```

**Prioridades Válidas:** `Low`, `Medium`, `High`

**Validación:**

- `priority`: requerido, enum
- `priority_justification`: requerido si `priority != "Unassigned"`, max 500 caracteres, sin HTML tags
- No puede volver a `Unassigned` una vez asignada

**Response 200 OK:**

```json
{
  "id": 1,
  "priority": "High",
  "priority_justification": "Cliente VIP solicitó escalada",
  "updated_at": "2026-02-25T10:45:00Z"
}
```

**Response 400 Bad Request:**

```json
{
  "error": "Campo 'priority_justification' es requerido"
}
```

**Response 403 Forbidden:** Usuario no tiene permisos (no es ADMIN).

```json
{
  "error": "No tienes permisos para cambiar la prioridad"
}
```

**Response 404 Not Found:** Ticket no existe.

**Eventos Publicados:** `TicketPriorityChanged`

---

### 💬 Tickets: Agregar Respuesta

#### POST /tickets/{id}/responses/

**Descripción:** Agrega una respuesta al ticket (solo ADMIN).

**Autorización:** Requiere rol `ADMIN`

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `id` | integer | ID del ticket |

**Request Body:**

```json
{
  "response_text": "Equipo está investigando el problema",
  "admin_id": "admin1"
}
```

**Validación:**

- `response_text`: requerido, string, max 1000 caracteres, sin HTML tags
- `admin_id`: requerido, string, max 100 caracteres

**Response 201 Created:**

```json
{
  "id": 15,
  "ticket_id": 1,
  "response_text": "Equipo está investigando el problema",
  "admin_id": "admin1",
  "created_at": "2026-02-25T10:50:00Z"
}
```

**Response 400 Bad Request:**

```json
{
  "error": "Campo 'response_text' es requerido"
}
```

**Response 403 Forbidden:** Usuario no tiene permisos (no es ADMIN).

**Response 404 Not Found:** Ticket no existe.

**Eventos Publicados:** `TicketResponseAdded`

---

### 📍 Tickets: Listar por Usuario

#### GET /tickets/my-tickets/{user_id}/

**Descripción:** Lista todos los tickets de un usuario específico.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `user_id` | string | ID del usuario |

**Query Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `page` | integer | Número de página (default: 1) |
| `page_size` | integer | Elementos por página (default: 20) |
| `status` | string | Filtrar por estado |

**Response 200 OK:**

```json
{
  "count": 15,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "title": "Bug crítico",
      "status": "IN_PROGRESS",
      "priority": "High",
      "user_id": "user1",
      "created_at": "2026-02-24T14:00:00Z"
    }
  ]
}
```

**Response 404 Not Found:** Usuario no existe.

**Response 500 Internal Server Error:** Error inesperado en el servidor.

---

### 📊 Códigos de Respuesta HTTP

| Código | Significado | Caso de Uso |
|--------|-------------|-------------|
| `200` | OK | Operación exitosa (GET, PATCH exitosos) |
| `201` | Created | Recurso creado (POST exitoso) |
| `400` | Bad Request | Validación fallida, datos inválidos, transición no permitida |
| `401` | Unauthorized | Token faltante o expirado |
| `403` | Forbidden | Usuario autenticado pero sin permisos |
| `404` | Not Found | Recurso no encontrado |
| `500` | Internal Server Error | Error inesperado en el servidor (no capturado) |

---

### 🔒 Manejo de Errores

**Errores Esperados (4xx):**

```json
{
  "error": "Descripción específica del problema"
}
```

**Errores del Servidor (5xx):**

```json
{
  "error": "Error interno del servidor"
}
```

*Nota: Los errores 500 **nunca** exponen stacktraces o detalles técnicos internos en producción.*

---

## Resumen Ejecutivo

| Categoría de Dolor | # Problemas | Beneficio Principal de Clean Architecture |
|---|---|---|
| Violaciones DDD / Capas | 3 | **Dependency Rule** fuerza separación estricta; el framework es un detalle enchufable |
| Dominio inconsistente | 5 | **Entities como fuente de verdad** para reglas, eventos y validación |
| Aplicación con leaks | 3 | **Use Cases puros** con Commands/Queries inmutables y autorización externalizada |
| Infraestructura frágil | 4 | **Puertos e interfaces** permiten reemplazar implementaciones sin tocar lógica |
| Presentación acoplada | 4 | **Adaptadores delgados** con exception handling centralizado y DTOs explícitos |
| Tests desorganizados | 3 | **Tests por capa** con un solo runner y cobertura medible |
| DevOps/Config | 4 | **Servicio autónomo** con configuración inyectable y health checks |

### Conclusión

La mayoría de los dolores identificados **no son bugs, sino síntomas de acoplamiento entre capas**. Clean Architecture no resuelve cada problema individualmente — resuelve la causa raíz: la ausencia de boundaries estrictos entre negocio, aplicación, infraestructura y presentación.

La migración no requiere un big-bang rewrite. Se puede ejecutar incrementalmente:

1. **Quick wins (1-2 días):** Exception handler centralizado, logging, paginación, fields explícitos en serializer.
2. **Medio plazo (1-2 semanas):** Entidad `TicketResponse`, UUIDs en dominio, Commands completos, eliminación de `ModelViewSet`.
3. **Largo plazo (1 mes+):** Outbox pattern, connection pooling en RabbitMQ, reorganización de tests por capa, health checks.

Cada paso reduce fricción y acerca el sistema a una arquitectura donde **las reglas de negocio son independientes del framework, la base de datos y el broker de mensajería**.
