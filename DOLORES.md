# Dolores (Pain Points) — Backend Ticket Service

Documento de análisis de problemas, deuda técnica y puntos de fricción identificados a partir de la estructura actual del repositorio.

---

## 1. Violaciones a la Arquitectura DDD

### 1.1 El ViewSet accede directamente al ORM (bypass del dominio)

**Archivos afectados:** `tickets/views.py` (líneas 206–217, 264–273, 331–337)

A pesar de que la arquitectura define que las vistas son *thin controllers* que delegan a use cases, varios métodos del `TicketViewSet` acceden directamente a `Ticket.objects` y `TicketResponse.objects`:

- **`my_tickets()`**: Ejecuta `Ticket.objects.filter(user_id=...)` sin pasar por el repositorio ni por un use case.
- **`_list_responses()`**: Ejecuta `Ticket.objects.get(pk=...)` y `TicketResponse.objects.filter(...)` directamente.
- **`_create_response()`**: Ejecuta `Ticket.objects.get(pk=...)` y `TicketResponse.objects.create(...)` directamente.

**Impacto:** Rompe la separación de capas y crea dependencias directas de la capa de presentación al ORM de Django, saltándose el repositorio y las entidades de dominio.

### 1.2 El modelo `TicketResponse` no tiene entidad de dominio

**Archivos afectados:** `tickets/models.py`, `tickets/domain/entities.py`

Existe un modelo ORM `TicketResponse` pero no existe una entidad de dominio equivalente. Las respuestas se crean y consultan directamente via ORM desde el ViewSet, sin representación en la capa de dominio. Esto significa que:

- No hay reglas de negocio encapsuladas para `TicketResponse` como entidad.
- El repositorio (`TicketRepository`) no tiene métodos para gestionar respuestas.
- La validación está dispersa entre el serializer, el entity `Ticket.add_response()` y el ViewSet.

### 1.3 `queryset` y `serializer_class` en el ViewSet se basan en el ORM

**Archivo afectado:** `tickets/views.py` (líneas 50–51)

```python
queryset = Ticket.objects.all().order_by("-created_at")
serializer_class = TicketSerializer
```

El ViewSet hereda de `ModelViewSet`, lo que expone automáticamente operaciones CRUD basadas en ORM (`list`, `retrieve`, `update`, `destroy`) que conviven con las acciones que sí usan DDD (`perform_create`, `change_status`, `change_priority`). Esto genera una dualidad donde algunos flujos pasan por el dominio y otros no.

---

## 2. Problemas en la Capa de Dominio

### 2.1 `add_response()` no genera evento de dominio

**Archivo afectado:** `tickets/domain/entities.py` (método `add_response`)

El método `add_response()` valida reglas de negocio pero **no genera el evento `TicketResponseAdded`**. El evento se genera manualmente en el use case (`AddTicketResponseUseCase`), violando el patrón establecido donde `change_status()` y `change_priority()` generan sus eventos dentro de la entidad.

**Inconsistencia:** Dos patrones distintos de generación de eventos coexisten en el mismo diseño.

### 2.2 `TicketCreated` no se genera desde la entidad

**Archivo afectado:** `tickets/application/use_cases.py` (línea 89–99)

El evento `TicketCreated` se construye manualmente en `CreateTicketUseCase.execute()`, no desde la entidad ni desde la factory. El comentario en `Ticket.create()` dice *"El evento TicketCreated se genera al persistir porque necesitamos el ID asignado por la BD"*, lo cual es un smell: la generación de eventos está acoplada a una limitación de infraestructura (ID auto-generado por la BD).

### 2.3 Constantes de estado y prioridad duplicadas entre dominio y ORM

**Archivos afectados:** `tickets/domain/entities.py`, `tickets/models.py`

Las constantes `OPEN`, `IN_PROGRESS`, `CLOSED`, `PRIORITY_UNASSIGNED`, etc. están definidas tanto en la entidad de dominio como en el modelo ORM, sin un origen único de verdad (*single source of truth*). Si se agrega un nuevo estado o prioridad, hay que mantenerlo en dos lugares.

### 2.4 La entidad `Ticket` usa `datetime.now()` directamente

**Archivo afectado:** `tickets/domain/entities.py` (múltiples líneas)

Las llamadas a `datetime.now()` están hardcodeadas dentro de `change_status()`, `change_priority()` y `Ticket.create()`. Esto:

- Impide la inyección de un *clock* para testing determinista.
- Dificulta la reproducibilidad de tests que dependan del tiempo.

### 2.5 Validación de HTML/XSS ausente en `add_response()`

**Archivo afectado:** `tickets/domain/entities.py`

El método `add_response()` valida texto vacío y longitud máxima, pero **no valida contenido HTML/XSS**. Mientras la factory valida `title` y `description` contra HTML peligroso, el texto de las respuestas no tiene esta protección en ninguna capa (ni dominio, ni serializer).

---

## 3. Problemas en la Capa de Aplicación

### 3.1 `ChangeTicketPriorityCommand` usa `getattr` para campos dinámicos

**Archivo afectado:** `tickets/application/use_cases.py` (líneas 193, 207)

```python
user_role = getattr(command, "user_role", None)
justification = getattr(command, "justification", None)
```

El command `ChangeTicketPriorityCommand` es un `@dataclass` con solo `ticket_id` y `new_priority`, pero el use case accede a `justification` y `user_role` via `getattr`, y estos se asignan dinámicamente en el ViewSet:

```python
command.justification = justification
command.user_role = user_role
```

**Impacto:** Se rompe la inmutabilidad implícita de los commands como DTOs. Los campos deberían estar definidos explícitamente en el dataclass.

### 3.2 Lógica de autorización en el use case (leak de responsabilidad)

**Archivo afectado:** `tickets/application/use_cases.py` (líneas 192–194)

```python
if user_role is not None and user_role != "Administrador":
    raise DomainException("Permiso insuficiente para cambiar la prioridad")
```

La verificación de permisos ("solo ADMIN puede cambiar prioridad") vive parcialmente en el use case y parcialmente en el ViewSet. La autorización no es una regla de dominio — es una preocupación de la capa de presentación o de un middleware, y su ubicación actual genera confusión.

### 3.3 Mapeo de roles hardcodeado entre capas

**Archivo afectado:** `tickets/views.py` (líneas 168–172)

```python
user_role = 'Administrador' if jwt_role.upper() == 'ADMIN' else jwt_role
```

El ViewSet traduce `"ADMIN"` (del JWT) a `"Administrador"` (que espera el use case). Este mapeo está hardcodeado y disperso, creando un acoplamiento frágil entre la representación del JWT y la lógica interna.

---

## 4. Problemas de Infraestructura

### 4.1 RabbitMQ: conexión nueva por cada evento publicado

**Archivo afectado:** `tickets/infrastructure/event_publisher.py` (líneas 97–124)

Cada llamada a `publish()` abre una conexión TCP nueva a RabbitMQ, declara el exchange, publica y cierra. No hay pool de conexiones ni reutilización.

**Impacto:**
- Overhead significativo en escenarios con múltiples eventos por request.
- Posible agotamiento de file descriptors bajo carga.
- Si RabbitMQ está caído, falla síncronamente y bloquea la request HTTP.

### 4.2 Sin mecanismo de resiliencia para publicación de eventos

**Archivo afectado:** `tickets/infrastructure/event_publisher.py`

No hay:
- **Retry logic** ante fallas de conexión.
- **Circuit breaker** para evitar cascada de fallos.
- **Outbox pattern** para garantizar consistencia entre persistencia y publicación.
- **Dead letter queue** para eventos fallidos.

Si RabbitMQ falla después de que el repositorio persistió un cambio, el evento se pierde permanentemente. La operación de negocio se completó pero el ecosistema de microservicios nunca se entera.

### 4.3 `to_django_model()` ejecuta un query adicional innecesario

**Archivo afectado:** `tickets/infrastructure/repository.py` (líneas 101–121)

El método `to_django_model()` (usado para serialización en respuestas HTTP) ejecuta `DjangoTicket.objects.get(pk=...)` cada vez. Esto duplica el query: primero el repositorio busca el ticket para ejecutar lógica de dominio, y luego se busca de nuevo para convertirlo a modelo Django para el serializer.

### 4.4 `print()` como logging

**Archivo afectado:** `tickets/infrastructure/event_publisher.py` (línea 125)

```python
print(f"Evento {message['event_type']} publicado: ...")
```

Se usa `print()` en lugar de `logging.getLogger()`. No hay framework de logging configurado para el servicio.

---

## 5. Problemas en la Capa de Presentación

### 5.1 Manejo de excepciones repetitivo y no estandarizado

**Archivo afectado:** `tickets/views.py`

Cada action (`change_status`, `change_priority`, `_create_response`) tiene su propio bloque `try/except` con la misma cadena de excepciones (`TicketAlreadyClosed`, `ValueError`, `DomainException`). No hay un **exception handler** centralizado de DRF que traduzca excepciones de dominio a respuestas HTTP.

**Impacto:** Código duplicado, riesgo de inconsistencia en códigos HTTP para la misma excepción, y mayor superficie de mantenimiento.

### 5.2 `my_tickets()` sin paginación

**Archivo afectado:** `tickets/views.py` (método `my_tickets`)

La consulta `Ticket.objects.filter(user_id=...)` retorna **todos** los tickets de un usuario sin paginación. Para usuarios con muchos tickets, esto genera:
- Respuestas HTTP grandes.
- Queries lentas a medida que crece la tabla.

El `queryset` principal del ViewSet tampoco tiene paginación configurada.

### 5.3 `fields = "__all__"` en el serializer

**Archivo afectado:** `tickets/serializer.py` (línea 78)

El uso de `fields = "__all__"` expone automáticamente cualquier campo nuevo que se agregue al modelo. El propio docstring lo advierte: *"Si se agregan campos sensibles al modelo en el futuro, se debe migrar a una lista explícita de campos"*.

### 5.4 Autenticación deshabilitada de facto para algunas acciones

**Archivo afectado:** `tickets/views.py`

El ViewSet hereda `IsAuthenticated` como permiso global (vía settings), pero `my_tickets()` no valida que el `user_id` del path coincida con el usuario autenticado. Cualquier usuario autenticado puede listar los tickets de otro usuario simplemente conociendo su `user_id`.

---

## 6. Problemas en la Suite de Tests

### 6.1 Archivos de test con nombres ambiguos/solapados

**Directorio afectado:** `tickets/tests/unit/`

Existen archivos con responsabilidades aparentemente duplicadas:
- `test_ticket_entity.py` y `test_ticket_responses.py` — ambos testean la entidad `Ticket`.
- `test_serializer_xss.py` y `test_xss_validation.py` — ambos testean validación XSS.
- `test_integration.py` dentro de `unit/` — nombre confuso, es un test unitario con nombre de integración.
- `test_infrastructure.py` en `unit/` — si testea infraestructura real (DB, RabbitMQ) debería estar en `integration/`.

### 6.2 Doble runner de tests (pytest + Django test runner)

**Archivos afectados:** `conftest.py`, documentación de tests

Los tests unitarios usan `pytest` y los de integración usan `python manage.py test`. Esto genera:
- Dos configuraciones distintas de BD (SQLite via conftest vs. la que Django gestione).
- Posibles inconsistencias de comportamiento entre runners.
- Complejidad innecesaria para nuevos desarrolladores.

### 6.3 Sin cobertura de código configurada

No hay configuración de `coverage`, `pytest-cov`, ni `.coveragerc`. El ratio test/producción de 2.4:1 mencionado en el README no está respaldado por métricas reales de cobertura.

---

## 7. Problemas de Configuración y DevOps

### 7.1 `load_dotenv` apunta a un path relativo fuera del proyecto

**Archivo afectado:** `ticket_service/settings.py` (línea 22)

```python
load_dotenv(BASE_DIR.parent.parent / ".env")
```

El path navega **dos niveles arriba** del directorio del proyecto. Esto asume una estructura de workspace específica (monorepo) y falla si el servicio se ejecuta de forma aislada.

### 7.2 Docker-compose con build context relativo

**Archivo afectado:** `docker-compose.yml` (línea 24)

```yaml
build:
  context: ./backend/ticket-service
```

El `docker-compose.yml` usa un path relativo (`./backend/ticket-service`) que sugiere que vive en un monorepo padre, pero está incluido en este repositorio. Si se ejecuta desde este repo directamente, el build context no existe.

### 7.3 Sin health check para el servicio backend

**Archivo afectado:** `docker-compose.yml`

La base de datos tiene `healthcheck` configurado, pero el servicio `backend` no. Otros servicios que dependan del backend no tienen forma de saber si ya está listo para recibir requests.

### 7.4 `runserver` en producción

**Archivo afectado:** `docker-compose.yml` (línea 32)

```yaml
command: >
  sh -c "python manage.py migrate &&
         python manage.py runserver 0.0.0.0:8000"
```

Se usa el servidor de desarrollo de Django (`runserver`) en el docker-compose. Para producción debería usarse `gunicorn` o `uvicorn`.

---

## 8. Deuda Técnica General

### 8.1 No hay `TicketResponseRepository`

Las operaciones CRUD de `TicketResponse` se realizan directamente via ORM desde el ViewSet, sin pasar por un repositorio. Esto es inconsistente con el patrón Repository aplicado a `Ticket`.

### 8.2 No hay validación de `updated_at`

No existe un campo `updated_at` en el modelo `Ticket`. No se puede saber cuándo fue la última modificación de un ticket sin consultar los eventos de dominio.

### 8.3 Sin versionamiento de API

Los endpoints están en `/api/tickets/` sin prefijo de versión (`/api/v1/tickets/`). Cambios breaking en el futuro obligarían a modificar todos los consumidores simultáneamente.

### 8.4 Ausencia de `__str__` y `__repr__` en la entidad de dominio

La entidad `Ticket` (dominio) es un `@dataclass` que genera un `__repr__` automático con todos los campos (incluyendo `_domain_events`). No hay `__str__` legible para debugging ni logging.

### 8.5 Magic strings dispersas

Valores como `"ADMIN"`, `"Administrador"`, `"access_token"`, `"role"` están hardcodeados en múltiples archivos sin centralización en constantes.

---

## Resumen por Severidad

| Severidad | # | Dolor |
|-----------|---|-------|
| **Alta** | 4.2 | Sin resiliencia en publicación de eventos (pérdida de datos) |
| **Alta** | 1.1 | ViewSet bypasea el dominio accediendo al ORM directamente |
| **Alta** | 5.4 | Falta de autorización en `my_tickets()` (IDOR) |
| **Media** | 4.1 | Conexión nueva a RabbitMQ por cada evento |
| **Media** | 1.2 | `TicketResponse` sin entidad de dominio |
| **Media** | 2.1 | Inconsistencia en generación de eventos de dominio |
| **Media** | 3.1 | Command con campos dinámicos vía `getattr` |
| **Media** | 5.1 | Manejo de excepciones duplicado |
| **Media** | 2.5 | Sin validación XSS en texto de respuestas |
| **Media** | 7.4 | `runserver` en Docker (no apto para producción) |
| **Baja** | 2.3 | Constantes duplicadas dominio/ORM |
| **Baja** | 2.4 | `datetime.now()` hardcodeado |
| **Baja** | 4.4 | `print()` como logging |
| **Baja** | 5.2 | Sin paginación |
| **Baja** | 5.3 | `fields = "__all__"` en serializer |
| **Baja** | 8.5 | Magic strings dispersas |
