# Plan de Pruebas y Gestión de Riesgos — Ticket Service v3.0

**Proyecto:** Backend Ticket Service (Microservicio de Gestión de Tickets)  
**Versión del Plan:** 3.0  
**Fecha:** 25 de Febrero de 2026  
**Autor:** Equipo de QA  

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Alcance y Objetivos](#2-alcance-y-objetivos)
3. [Niveles de Prueba](#3-niveles-de-prueba)
4. [Estrategia de Calidad](#4-estrategia-de-calidad)
5. [Herramientas y Entorno](#5-herramientas-y-entorno)
6. [Calendario de Pruebas](#6-calendario-de-pruebas)
7. [Gestión de Riesgos](#7-gestión-de-riesgos)
8. [Criterios de Entrada y Salida](#8-criterios-de-entrada-y-salida)
9. [Roles y Responsabilidades](#9-roles-y-responsabilidades)
10. [Entregables](#10-entregables)
11. [Métricas de Calidad](#11-métricas-de-calidad)
12. [Referencias ISTQB](#12-referencias-istqb)

---

## 1. Resumen Ejecutivo

Este documento establece el **Plan de Pruebas y Gestión de Riesgos** para el microservicio Backend Ticket Service, desarrollado con arquitectura Domain-Driven Design (DDD) y Event-Driven Architecture (EDA) sobre Django 6.0.2.

### Objetivos Principales

- **Garantizar la calidad** de los endpoints REST de la API de tickets
- **Validar la integridad** de la arquitectura DDD (Domain, Application, Infrastructure)
- **Verificar la seguridad** ante ataques XSS y vulnerabilidades comunes
- **Asegurar la consistencia** de eventos publicados a RabbitMQ
- **Identificar y mitigar riesgos** técnicos y funcionales del proyecto

### Contexto Técnico

| Aspecto | Detalle |
|---------|---------|
| **Framework** | Django 6.0.2 + Django REST Framework |
| **Lenguaje** | Python 3.12 |
| **Arquitectura** | DDD + EDA + CQRS simplificado |
| **Base de Datos** | PostgreSQL 16 (dev/prod), SQLite in-memory (tests) |
| **Message Broker** | RabbitMQ (exchange fanout `tickets`) |
| **Autenticación** | JWT stateless (HttpOnly cookie) |
| **Contenedores** | Docker / podman-compose |

---

## 2. Alcance y Objetivos

### 2.1 Alcance de las Pruebas

#### ✅ Incluido en el Alcance

**Funcional:**
- **CRUD de Tickets:** Creación, consulta, actualización de estado y prioridad
- **Gestión de Respuestas:** Creación y listado de respuestas asociadas a tickets
- **Máquina de Estados:** Transiciones `OPEN → IN_PROGRESS → CLOSED`
- **Prioridades:** Transiciones y validación de justificaciones (`Low → High`)
- **Validación XSS:** Rechazo de HTML/JS malicioso en título y descripción
- **Autenticación JWT:** Validación de tokens en cookies HttpOnly
- **Eventos de Dominio:** Publicación correcta a RabbitMQ

**No Funcional:**
- **Performance:** Tiempo de respuesta < 200ms (p95) para operaciones CRUD
- **Seguridad:** Protección contra XSS, CSRF, inyección SQL
- **Disponibilidad:** Manejo de errores 500 genéricos sin exponer stack traces
- **Escalabilidad:** Concurrencia hasta 50 usuarios simultáneos

**Arquitectura:**
- **Independencia de Dominio:** Entidades libres de framework (testing sin Django)
- **Inversión de Dependencias:** Repositorios abstraídos mediante interfaces
- **Separación de Responsabilidades:** ViewSet → Use Case → Entity → Repository

#### ❌ Excluido del Alcance

- Frontend (fuera del repositorio)
- Integración con servicio de usuarios (dependencia externa)
- Pruebas de carga extrema (> 100 usuarios concurrentes)
- Auditoría de infraestructura (configuración de servidores)

### 2.2 Objetivos de Calidad

1. **Cobertura de Código:** ≥ 85% en líneas ejecutadas (pytest-cov)
2. **Defectos Críticos:** 0 defectos críticos en producción
3. **Regresión:** 100% de tests pasando antes de cada release
4. **Documentación:** Todos los casos de prueba documentados y reproducibles
5. **Automatización:** ≥ 90% de pruebas funcionales automatizadas

---

## 3. Niveles de Prueba

Siguiendo la pirámide de pruebas (ISTQB Foundation §5.2), se definen tres niveles con prioridades diferenciadas:

### 3.1 Pruebas Unitarias (Base de la Pirámide)

**Objetivo:** Verificar componentes aislados sin dependencias externas.

**Alcance:**
- **Domain Layer:**
  - `Ticket` entity: máquina de estados, validaciones de prioridad
  - `TicketResponse` entity: validación de contenido y límites
  - `TicketFactory`: creación válida, rechazo XSS
  - Domain events: inmutabilidad y estructura
  - Domain exceptions: jerarquía de errores

- **Validation Layer:**
  - Serializers: validación XSS en título/descripción
  - Input sanitization: detección de patrones peligrosos

**Herramientas:**
- pytest (runner)
- pytest-mock (mocking)
- Cobertura: pytest-cov

**Ubicación:** `tickets/tests/unit/`

**Comandos:**
```bash
podman-compose exec backend pytest tickets/tests/unit/ -v --cov=tickets/domain
```

**Criterio de Éxito:** ≥ 90% cobertura en domain layer, 0 fallos.

---

### 3.2 Pruebas de Integración (Nivel Medio)

**Objetivo:** Validar interacción entre capas (Application → Domain → Infrastructure).

**Alcance:**
- **Use Cases:**
  - `CreateTicketUseCase`: persistencia + publicación de evento
  - `UpdateTicketStatusUseCase`: transición válida + evento
  - `AddResponseUseCase`: validación de ticket cerrado

- **Repository Pattern:**
  - `DjangoTicketRepository`: mapeo ORM ↔ Domain Entity
  - Transacciones y rollback automático

- **Event Publisher:**
  - `RabbitMQEventPublisher`: traducción y envío de eventos
  - Verificación de estructura JSON en colas

- **API Endpoints (con Django TestCase):**
  - POST `/api/tickets/` → 201 Created
  - GET `/api/tickets/my-tickets/` → 200 OK (filtrado por user_id)
  - POST `/api/tickets/{id}/responses/` → 201 Created (si ticket abierto)
  - PATCH `/api/tickets/{id}/` → 400 Bad Request (transición inválida)
  - XSS en request body → 400 Bad Request

**Herramientas:**
- Django TestCase (base de datos real: SQLite in-memory)
- Django REST Framework APIClient
- RabbitMQ test fixtures (mocking con unittest.mock)

**Ubicación:** `tickets/tests/integration/`

**Comandos:**
```bash
podman-compose exec backend python manage.py test tickets.tests.integration --verbosity=2
```

**Criterio de Éxito:** 100% de flujos CRUD + eventos verificados, 0 fallos.

---

### 3.3 Pruebas End-to-End (Cima de la Pirámide)

**Objetivo:** Validar flujos completos de usuario desde HTTP hasta persistencia + eventos.

**Alcance:**
- **Flujo Completo de Ticket:**
  1. Usuario crea ticket (`OPEN`)
  2. Agente actualiza a `IN_PROGRESS`
  3. Agente añade respuesta
  4. Agente cierra ticket (`CLOSED`)
  5. Validar que ticket cerrado rechaza cambios

- **Flujo de Prioridad:**
  1. Ticket creado sin prioridad (`Unassigned`)
  2. Agente asigna `Low` con justificación
  3. Agente escala a `High` con justificación
  4. Validar rechazo de downgrade a `Unassigned`

- **Flujo de Errores:**
  1. Request con XSS → 400 + mensaje claro
  2. Ticket no encontrado → 404
  3. Error interno (mock) → 500 sin stack trace

- **Pruebas de Performance:**
  - 10 tickets creados en < 2 segundos
  - 50 consultas concurrentes sin errores

**Herramientas:**
- pytest + Django TestCase
- locust (pruebas de carga básicas)
- Stack completo en contenedores (docker-compose)

**Ubicación:** `tickets/tests/e2e/`

**Comandos:**
```bash
podman-compose exec backend python manage.py test tickets.tests.e2e --verbosity=2
```

**Criterio de Éxito:** Todos los flujos de usuario validados, latencia < 200ms (p95).

---

## 4. Estrategia de Calidad

### 4.1 Enfoque de Testing (ISTQB §5.2.1)

**Estrategia Seleccionada:** **Híbrida (Analítica + Reactiva)**

- **Analítica (Risk-Based Testing):**
  - Priorizar pruebas según criticidad (ver sección 7: Gestión de Riesgos)
  - Máquina de estados de tickets (Alta Prioridad)
  - Validación XSS (Alta Prioridad)
  - Publicación de eventos (Media Prioridad)

- **Reactiva (Exploración):**
  - Sesiones de testing exploratorio post-despliegue
  - Pruebas de regresión ad-hoc ante bugs reportados

### 4.2 Técnicas de Diseño de Pruebas (ISTQB §4)

| Técnica | Aplicación en el Proyecto |
|---------|---------------------------|
| **Partición de Equivalencia** | Estados de ticket (`OPEN`, `IN_PROGRESS`, `CLOSED`), Prioridades (`Unassigned`, `Low`, `Medium`, `High`) |
| **Análisis de Valores Límite** | Longitud de título (255 chars), descripción (2000 chars), justificación prioridad (500 chars) |
| **Transición de Estados** | Matriz de transiciones válidas/inválidas de `status` |
| **Tabla de Decisiones** | Validación XSS: combinaciones de `<script>`, `onerror`, `javascript:` |
| **Pruebas Negativas** | Tickets cerrados no aceptan cambios, prioridad no puede regresar a `Unassigned` |

### 4.3 Estrategia de Datos de Prueba

**Datos Sintéticos:**
- Fixtures de tickets (`factories.py` con `faker`)
- Tokens JWT de prueba generados programáticamente
- Mensajes RabbitMQ simulados con payloads JSON válidos

**Datos Reales Anonimizados:**
- NO se utilizan datos de producción (cumplimiento GDPR)

**Gestión:**
- Repositorio `conftest.py` con fixtures de pytest
- Base de datos limpia antes de cada test (transaccional rollback)

---

## 5. Herramientas y Entorno

### 5.1 Herramientas de Prueba

| Herramienta | Propósito | Versión |
|-------------|-----------|---------|
| **pytest** | Runner de tests unitarios | ≥ 7.0 |
| **pytest-django** | Integración Django + pytest | ≥ 4.5 |
| **pytest-cov** | Medición de cobertura | ≥ 4.0 |
| **Django TestCase** | Tests de integración con DB | Django 6.0.2 |
| **DRF APIClient** | Tests de endpoints REST | ≥ 3.14 |
| **unittest.mock** | Mocking de RabbitMQ | stdlib |
| **locust** | Pruebas de carga | ≥ 2.15 |
| **bandit** | Análisis estático de seguridad | ≥ 1.7 |
| **flake8** | Linting de código | ≥ 6.0 |

### 5.2 Entorno de Pruebas

**Entornos Disponibles:**

1. **Local (Desarrollador):**
   - SQLite in-memory
   - RabbitMQ mockeado
   - Ejecución: `pytest`

2. **Integración (CI/CD):**
   - PostgreSQL en contenedor
   - RabbitMQ real (exchange fanout)
   - Ejecución: `podman-compose up -d && pytest`

3. **Staging (Pre-producción):**
   - Réplica de producción
   - Datos sintéticos
   - Tests E2E automatizados

**Configuración de Ambientes:**

```python
# settings_test.py (usado por conftest.py)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Mock RabbitMQ en tests unitarios
@pytest.fixture
def mock_event_publisher(monkeypatch):
    mock = Mock(spec=EventPublisher)
    return mock
```

### 5.3 Infraestructura

**Stack de Contenedores (docker-compose.yml):**
- `backend` (Ticket Service)
- `db` (PostgreSQL 16)
- `rabbitmq` (RabbitMQ 3.x con management plugin)

**Puertos de Test:**
- API REST: `http://localhost:8000/api/tickets/`
- RabbitMQ Management: `http://localhost:15672`

---

## 6. Calendario de Pruebas

### 6.1 Fases del Proyecto

| Fase | Actividades de QA | Duración | Responsable |
|------|-------------------|----------|-------------|
| **Sprint 1: Fundamentos** | - Setup de entorno de pruebas<br>- Definición de fixtures<br>- Pruebas unitarias de dominio | 2 semanas | QA Engineer |
| **Sprint 2: Integración** | - Tests de repositorio<br>- Tests de use cases<br>- Tests de API endpoints | 2 semanas | QA Engineer + Dev |
| **Sprint 3: E2E** | - Flujos completos de tickets<br>- Tests de seguridad XSS<br>- Performance básica | 2 semanas | QA Lead |
| **Sprint 4: Estabilización** | - Corrección de defectos<br>- Optimización de tests<br>- Documentación final | 1 semana | Todo el equipo |

### 6.2 Ejecución Diaria

**Integración Continua (CI Pipeline):**

```yaml
# .github/workflows/test.yml (ejemplo conceptual)
on: [push, pull_request]

jobs:
  test:
    steps:
      - name: Unit Tests
        run: pytest tickets/tests/unit/ -v --cov=tickets
      
      - name: Integration Tests
        run: python manage.py test tickets.tests.integration
      
      - name: E2E Tests
        run: python manage.py test tickets.tests.e2e
      
      - name: Security Scan
        run: bandit -r tickets/
      
      - name: Coverage Report
        run: pytest --cov-report=html --cov-report=term
```

**Frecuencia de Ejecución:**
- **Unitarias:** Cada commit (< 30 segundos)
- **Integración:** Cada pull request (< 2 minutos)
- **E2E:** Cada merge a `main` (< 5 minutos)
- **Performance:** Semanal (viernes tarde)

---

## 7. Gestión de Riesgos

Siguiendo ISTQB Foundation §5.5 (Risk-Based Testing), se identifican, evalúan y mitigan riesgos técnicos y funcionales.

### 7.1 Matriz de Riesgos

| ID | Riesgo | Probabilidad | Impacto | Severidad | Estrategia | Mitigación |
|----|--------|--------------|---------|-----------|------------|------------|
| **R01** | **Violación de máquina de estados** (ticket cerrado acepta cambios) | Media | Crítico | **ALTA** | Prevenir | - Tests exhaustivos de transiciones inválidas<br>- Validación en entidad de dominio<br>- Tests de regresión automatizados |
| **R02** | **Ataque XSS exitoso** (script malicioso en UI) | Baja | Crítico | **ALTA** | Prevenir | - Doble validación: serializer + factory<br>- Tests con payloads OWASP Top 10<br>- Revisión de código por seguridad |
| **R03** | **Pérdida de eventos** (RabbitMQ caído) | Media | Alto | **ALTA** | Detectar + Recuperar | - Health check de RabbitMQ (logs)<br>- Retry policy con exponential backoff<br>- Dead letter queue (DLQ) para mensajes fallidos |
| **R04** | **Inconsistencia ORM ↔ Dominio** (mapeo incorrecto en repositorio) | Media | Alto | **ALTA** | Prevenir | - Tests de integración de repositorio<br>- Validación bidireccional: `to_domain()` + `from_domain()`<br>- Aserciones explícitas en tests |
| **R05** | **Dependencia circular** (ViewSet → ORM directo) | Alta | Medio | **MEDIA** | Prevenir | - Código review obligatorio<br>- Linting custom (detección de imports)<br>- Arquitectura documentada (ARCHITECTURE.md) |
| **R06** | **Stack trace expuesto en 500** | Baja | Medio | **MEDIA** | Prevenir | - Middleware genérico de errores<br>- Tests de error handling<br>- Configuración `DEBUG=False` en prod |
| **R07** | **Performance degradada** (> 500ms p95) | Media | Medio | **MEDIA** | Detectar | - Tests de performance semanales<br>- Profiling con django-silk (dev)<br>- Índices de base de datos |
| **R08** | **Falta de cobertura en edge cases** | Alta | Bajo | **BAJA** | Aceptar | - Priorizar casos críticos<br>- Testing exploratorio mensual<br>- Backlog de mejoras |

### 7.2 Estrategias de Mitigación Detalladas

#### R01: Violación de Máquina de Estados

**Escenario de Fallo:**  
Un ticket en estado `CLOSED` acepta una actualización de prioridad o una nueva respuesta, violando la regla de negocio.

**Impacto:**
- Inconsistencia de datos
- Pérdida de confianza en el sistema
- Posible corrupción de métricas

**Plan de Mitigación:**
1. **Prevención:**
   - Validación en `Ticket.update_status()` rechaza transiciones inválidas
   - Validación en `Ticket.change_priority()` verifica que `status != CLOSED`
   - Validación en `AddResponseUseCase` verifica `ticket.is_closed() == False`

2. **Detección:**
   - Tests de integración: `test_ticket_workflow.py::test_closed_ticket_rejects_changes()`
   - Tests E2E: `test_ticket_lifecycle.py::test_cannot_modify_closed_ticket()`

3. **Recuperación:**
   - Si se detecta en producción: rollback del cambio + log de auditoría
   - Investigación de root cause (código review)

**Indicadores:**
- 0 defectos de este tipo en producción
- 100% cobertura de tests de transiciones

---

#### R02: Ataque XSS Exitoso

**Escenario de Fallo:**  
Un atacante envía un payload con `<script>alert('XSS')</script>` en el título del ticket, que es almacenado y renderizado en el frontend.

**Impacto:**
- Robo de tokens JWT
- Ejecución arbitraria de código en navegadores de usuarios
- Violación de seguridad crítica

**Plan de Mitigación:**
1. **Prevención:**
   - **Capa 1 (Serializer):** `TicketSerializer._check_dangerous_input()` rechaza inputs con HTML/JS
   - **Capa 2 (Domain Factory):** `TicketFactory.create()` valida nuevamente antes de crear entidad
   - **Capa 3 (Frontend):** Escapado de HTML en renderizado (fuera de alcance de este backend)

2. **Detección:**
   - Tests unitarios: `test_serializer_xss.py` (13 casos de XSS)
   - Tests de API: `test_xss_api.py::test_endpoint_rejects_xss_in_title()`
   - Escaneo estático: `bandit -r tickets/` detecta uso inseguro de `eval()`, `exec()`

3. **Respuesta:**
   - Si se detecta en producción: sanitización inmediata de registros afectados
   - Bloqueo del usuario malicioso (IP + user_id)

**Indicadores:**
- 0 vulnerabilidades XSS en auditoría de seguridad
- 100% de payloads OWASP rechazados

---

#### R03: Pérdida de Eventos (RabbitMQ Caído)

**Escenario de Fallo:**  
RabbitMQ está caído durante la creación de un ticket. El ticket se persiste en DB pero el evento `TicketCreated` no se publica.

**Impacto:**
- Inconsistencia entre servicios
- Otros microservicios no reciben notificaciones
- Auditoría incompleta

**Plan de Mitigación:**
1. **Prevención:**
   - Health check de RabbitMQ antes de publicar evento (opcional)
   - Transaccionalidad: persistir + publicar en la misma transacción (outbox pattern futuro)

2. **Detección:**
   - Logs de errores en `RabbitMQEventPublisher.publish()`
   - Monitoreo de cola de eventos (dashboard de RabbitMQ)

3. **Recuperación:**
   - **Retry Policy:** 3 intentos con backoff exponencial (1s, 2s, 4s)
   - **Dead Letter Queue (DLQ):** Eventos fallidos redirigidos a `tickets.dlq`
   - **Reconciliación:** Job batch diario que republica eventos faltantes

**Indicadores:**
- < 0.1% de eventos perdidos
- Tiempo de recuperación < 5 minutos

---

#### R04: Inconsistencia ORM ↔ Dominio

**Escenario de Fallo:**  
`DjangoTicketRepository.save()` mapea incorrectamente `Ticket` entity → `TicketModel` ORM, perdiendo datos del campo `priority_justification`.

**Impacto:**
- Pérdida de datos
- Violación de reglas de dominio
- Bugs silenciosos difíciles de detectar

**Plan de Mitigación:**
1. **Prevención:**
   - Mapeo explícito bidireccional:
     ```python
     # to_domain (ORM → Entity)
     priority_justification=model.priority_justification or ""
     
     # from_domain (Entity → ORM)
     model.priority_justification = entity.priority_justification
     ```
   - Tests de ida y vuelta: `assert entity == repo.save(entity).reload()`

2. **Detección:**
   - Tests de integración: `test_ticket_repository.py::test_priority_justification_persisted()`
   - Validación en tests: comparación campo por campo

**Indicadores:**
- 100% de campos de dominio mapeados correctamente
- 0 discrepancias en tests de repositorio

---

#### R05: Dependencia Circular (ViewSet → ORM)

**Escenario de Fallo:**  
Un desarrollador añade un método custom en `TicketViewSet` que ejecuta `Ticket.objects.filter()` directamente, bypaseando el dominio.

**Impacto:**
- Violación de arquitectura DDD
- Lógica de negocio duplicada
- Dificultad para mantener tests

**Plan de Mitigación:**
1. **Prevención:**
   - **Código Review Obligatorio:** PR checklist verifica ausencia de `models.` en `views.py`
   - **Linting Custom:** Script `check_deprecated_usage.py` detecta imports prohibidos:
     ```python
     # En views.py
     from tickets.models import Ticket  # ❌ Prohibido
     from tickets.application.use_cases import CreateTicketUseCase  # ✅ Correcto
     ```

2. **Detección:**
   - CI pipeline ejecuta `check_deprecated_usage.py` en cada PR
   - Documentación: `ARCHITECTURE.md` explica la regla

**Indicadores:**
- 0 imports prohibidos en `views.py`
- 100% de PRs revisados por arquitectura

---

#### R06: Stack Trace Expuesto en 500

**Escenario de Fallo:**  
Un error no manejado (e.g., `KeyError` en un use case) devuelve un 500 con stack trace completo, exponiendo rutas internas del sistema.

**Impacto:**
- Fuga de información sensible (rutas, versiones de librerías)
- Facilita ataques dirigidos

**Plan de Mitigación:**
1. **Prevención:**
   - Middleware genérico de errores (`tickets/infrastructure/error_handler.py`):
     ```python
     def handle_500(request, exception):
         logger.error(f"Unhandled: {exception}", exc_info=True)
         return JsonResponse({"error": "Internal server error"}, status=500)
     ```
   - Configuración: `DEBUG=False` en staging/producción

2. **Detección:**
   - Tests de integración: `test_generic_500.py::test_internal_error_no_stack_trace()`
   - Validación: respuesta JSON no contiene `Traceback`

**Indicadores:**
- 0 stack traces en respuestas de producción
- 100% de errores 500 logueados internamente

---

#### R07: Performance Degradada

**Escenario de Fallo:**  
Consultas N+1 en `GET /api/tickets/my-tickets/` causan latencia > 500ms con 100+ tickets.

**Impacto:**
- Experiencia de usuario pobre
- Timeouts en frontend
- Carga excesiva en base de datos

**Plan de Mitigación:**
1. **Prevención:**
   - `select_related()` y `prefetch_related()` en queries ORM
   - Índices en columnas frecuentes (`user_id`, `status`)

2. **Detección:**
   - Tests de performance: `test_performance.py::test_my_tickets_under_200ms()`
   - Profiling semanal con `django-silk` (dev)

3. **Optimización:**
   - Si p95 > 200ms: análisis de queries con `EXPLAIN`
   - Caché de resultados (Redis futuro)

**Indicadores:**
- p95 < 200ms para operaciones CRUD
- 0 queries N+1 en hot paths

---

#### R08: Falta de Cobertura en Edge Cases

**Escenario de Fallo:**  
Casos raros (e.g., ticket con 1000 respuestas, prioridad cambiada 50 veces) no están cubiertos por tests.

**Impacto:**
- Bugs en producción en situaciones inusuales
- Degradación gradual de calidad

**Plan de Mitigación:**
1. **Aceptación:**
   - Cobertura exhaustiva de edge cases no es costo-efectiva
   - Priorizar casos basados en probabilidad × impacto

2. **Monitoreo:**
   - Testing exploratorio mensual (sesiones de 2 horas)
   - Backlog de "nice-to-have tests" revisado trimestralmente

**Indicadores:**
- ≥ 85% cobertura de código (balance tiempo/riesgo)
- Backlog de mejoras actualizado mensualmente

---

### 7.3 Plan de Contingencia

**Criterios de Abortar Release:**
- Cualquier defecto de **Severidad ALTA** no resuelto
- < 80% de cobertura de código
- Fallo en > 5% de tests automatizados

**Rollback:**
- Despliegue con Docker tags versionados (`backend:v1.2.3`)
- Rollback automático si health check falla post-deploy
- Plan de comunicación: notificar a stakeholders en < 15 minutos

---

## 8. Criterios de Entrada y Salida

### 8.1 Criterios de Entrada (Entry Criteria)

**Para iniciar testing de un sprint:**

- [ ] Código mergeado a rama de testing (`develop` o `staging`)
- [ ] Entorno de pruebas disponible (contenedores levantados)
- [ ] Fixtures y datos de prueba preparados
- [ ] Test cases documentados en el plan de pruebas
- [ ] Dependencias externas mockeadas (RabbitMQ, servicios externos)

**Para iniciar testing E2E:**

- [ ] Todas las pruebas unitarias e integración pasando (100%)
- [ ] Stack completo desplegado (DB + Backend + RabbitMQ)
- [ ] Credenciales JWT de prueba generadas
- [ ] Datos sintéticos cargados en base de datos

### 8.2 Criterios de Salida (Exit Criteria)

**Para finalizar testing de un sprint:**

- [ ] ≥ 85% cobertura de código
- [ ] 100% de tests de integración pasando
- [ ] 0 defectos de severidad ALTA o CRÍTICA abiertos
- [ ] ≤ 3 defectos de severidad MEDIA abiertos (priorizados para próximo sprint)
- [ ] Reporte de defectos generado y revisado
- [ ] Métricas de calidad dentro de umbrales aceptables

**Para aprobar release a producción:**

- [ ] 100% de tests E2E pasando
- [ ] Tests de seguridad (bandit) sin vulnerabilidades críticas
- [ ] Performance tests: p95 < 200ms
- [ ] Documentación actualizada (README, API docs)
- [ ] Aprobación del QA Lead y Product Owner
- [ ] Plan de rollback documentado

---

## 9. Roles y Responsabilidades

| Rol | Responsabilidades | Persona |
|-----|-------------------|---------|
| **QA Lead** | - Definir estrategia de testing<br>- Revisar plan de pruebas<br>- Aprobar releases<br>- Gestión de riesgos | [Nombre] |
| **QA Engineer** | - Diseñar y ejecutar casos de prueba<br>- Automatizar tests<br>- Reportar defectos<br>- Mantener fixtures | [Nombre] |
| **Backend Developer** | - Escribir tests unitarios<br>- Corregir defectos<br>- Code review de tests<br>- Soporte a QA | [Nombre] |
| **DevOps Engineer** | - Mantener entornos de prueba<br>- CI/CD pipeline<br>- Monitoreo de métricas<br>- Rollback en caso de emergencia | [Nombre] |
| **Product Owner** | - Validar escenarios de prueba<br>- Priorizar corrección de defectos<br>- Aprobar criterios de aceptación | [Nombre] |

---

## 10. Entregables

### 10.1 Documentación

| Entregable | Descripción | Responsable | Plazo |
|------------|-------------|-------------|-------|
| **Plan de Pruebas (este documento)** | Estrategia, niveles, herramientas, riesgos | QA Lead | Sprint 1 |
| **Test Cases Detallados** | Casos de prueba por funcionalidad (Gherkin) | QA Engineer | Sprint 2 |
| **Reporte de Cobertura** | Cobertura de código (pytest-cov HTML) | QA Engineer | Cada sprint |
| **Reporte de Defectos** | Lista de bugs encontrados y estado | QA Engineer | Semanal |
| **Métricas de Calidad** | Dashboard de KPIs (cobertura, defectos, performance) | QA Lead | Mensual |

### 10.2 Artefactos de Código

- **Test Suites:**
  - `tickets/tests/unit/` (> 50 tests)
  - `tickets/tests/integration/` (> 30 tests)
  - `tickets/tests/e2e/` (> 10 tests)

- **Fixtures:**
  - `conftest.py` (fixtures globales de pytest)
  - `tickets/tests/factories.py` (generadores de datos)

- **Scripts de Automatización:**
  - `.github/workflows/test.yml` (CI pipeline)
  - `check_deprecated_usage.py` (linting custom)

---

## 11. Métricas de Calidad

### 11.1 KPIs Principales

| Métrica | Objetivo | Medición | Frecuencia |
|---------|----------|----------|------------|
| **Cobertura de Código** | ≥ 85% | pytest-cov | Cada commit |
| **Tasa de Defectos** | < 5 defectos/100 LoC | Manual | Semanal |
| **Defectos Críticos** | 0 en producción | Logs de prod | Diario |
| **Tiempo de Ejecución de Tests** | < 5 min (total) | CI pipeline | Cada commit |
| **Performance (p95)** | < 200ms | locust | Semanal |
| **Tasa de Falsos Positivos** | < 2% | Manual (revisión de fallos) | Sprint |

### 11.2 Dashboard de Métricas

**Herramientas:**
- **Coverage.py:** Reporte HTML de cobertura
- **pytest-html:** Reporte HTML de resultados de tests
- **Grafana + Prometheus:** Monitoreo de performance (futuro)

**Ejemplo de Reporte Semanal:**

```
=== Reporte de QA — Semana 8 ===
Cobertura:         87% (+2% vs semana anterior)
Tests Pasando:     142/145 (97.9%)
Tests Fallando:    3 (2 bugs conocidos, 1 nuevo)
Defectos Nuevos:   5 (2 críticos, 3 medios)
Defectos Cerrados: 8
Performance (p95): 178ms (✅ dentro de objetivo)
```

---

## 12. Referencias ISTQB

Este plan de pruebas se basa en los siguientes conceptos del **ISTQB Foundation Level** (páginas 60-67 típicamente):

### 12.1 Test Planning (§5.2)

- **Test Strategy:** Enfoque híbrido (analítico + reactivo)
- **Test Estimation:** Basado en complejidad de funcionalidades (story points)
- **Test Approach:** Scripted testing (automatizado) + exploratory testing (manual)

### 12.2 Test Monitoring and Control (§5.3)

- **Métricas:** Cobertura, tasa de defectos, tiempo de ejecución
- **Reporting:** Semanal a stakeholders, diario a equipo técnico
- **Control:** Ajuste de prioridades según avance y riesgos

### 12.3 Risk-Based Testing (§5.5)

- **Identificación de Riesgos:** Matriz de probabilidad × impacto
- **Análisis de Riesgos:** Clasificación en ALTA/MEDIA/BAJA
- **Mitigación:** Estrategias preventivas, detectivas y correctivas

### 12.4 Test Levels (§2.2)

- **Unit Testing:** Componentes aislados (domain entities)
- **Integration Testing:** Interacción entre capas (use cases + repository)
- **System Testing:** Sistema completo (E2E con stack de contenedores)

### 12.5 Test Design Techniques (§4)

- **Equivalence Partitioning:** Estados y prioridades de tickets
- **Boundary Value Analysis:** Límites de campos de texto
- **State Transition Testing:** Máquina de estados de tickets
- **Decision Table Testing:** Validación XSS (combinaciones de patrones)

### 12.6 Defect Management (§5.6)

- **Ciclo de Vida de Defectos:** New → Assigned → Fixed → Verified → Closed
- **Priorización:** Crítico > Alto > Medio > Bajo
- **Root Cause Analysis:** Investigación de defectos recurrentes

---

## Aprobaciones

| Rol | Nombre | Firma | Fecha |
|-----|--------|-------|-------|
| **QA Lead** | | | |
| **Backend Lead** | | | |
| **Product Owner** | | | |

---

## Control de Versiones

| Versión | Fecha | Autor | Cambios |
|---------|-------|-------|---------|
| 1.0 | 2026-02-01 | QA Team | Versión inicial |
| 2.0 | 2026-02-15 | QA Lead | Añadida sección de riesgos |
| 3.0 | 2026-02-25 | QA Team | Integración con ISTQB, plan completo E2E |

---

**Fin del Documento**

---

## Anexo A: Checklist de Ejecución de Tests

```bash
# 1. Levantar entorno
podman-compose up -d

# 2. Ejecutar tests unitarios
podman-compose exec backend pytest tickets/tests/unit/ -v --cov=tickets/domain

# 3. Ejecutar tests de integración
podman-compose exec backend python manage.py test tickets.tests.integration --verbosity=2

# 4. Ejecutar tests E2E
podman-compose exec backend python manage.py test tickets.tests.e2e --verbosity=2

# 5. Generar reporte de cobertura
podman-compose exec backend pytest --cov=tickets --cov-report=html --cov-report=term

# 6. Escaneo de seguridad
podman-compose exec backend bandit -r tickets/ -f json -o bandit-report.json

# 7. Linting
podman-compose exec backend flake8 tickets/ --count --show-source

# 8. Verificar estructura de arquitectura
python check_deprecated_usage.py
```

---

## Anexo B: Plantilla de Reporte de Defectos

```markdown
### Defecto #[ID]

**Título:** [Descripción breve]  
**Severidad:** [ ] Crítica [ ] Alta [ ] Media [ ] Baja  
**Prioridad:** [ ] Urgente [ ] Alta [ ] Normal [ ] Baja  
**Estado:** [ ] New [ ] Assigned [ ] Fixed [ ] Verified [ ] Closed  

**Descripción:**  
[Descripción detallada del problema]

**Pasos para Reproducir:**  
1. [Paso 1]
2. [Paso 2]
3. [Paso 3]

**Resultado Esperado:**  
[Qué debería ocurrir]

**Resultado Actual:**  
[Qué ocurre realmente]

**Entorno:**  
- SO: [Windows/Linux/macOS]
- Versión de backend: [v1.2.3]
- Base de datos: [PostgreSQL 16]

**Logs/Screenshots:**  
[Adjuntar logs relevantes o capturas de pantalla]

**Asignado a:** [Nombre del desarrollador]  
**Reportado por:** [Nombre del QA]  
**Fecha:** [YYYY-MM-DD]  
```

---

## Anexo C: Glosario de Términos

- **DDD (Domain-Driven Design):** Enfoque de arquitectura centrado en el dominio de negocio
- **EDA (Event-Driven Architecture):** Arquitectura basada en eventos asincrónicos
- **CQRS (Command Query Responsibility Segregation):** Separación de comandos (escritura) y queries (lectura)
- **XSS (Cross-Site Scripting):** Vulnerabilidad de seguridad por inyección de scripts
- **JWT (JSON Web Token):** Estándar de autenticación basado en tokens
- **ORM (Object-Relational Mapping):** Mapeo objeto-relacional (Django ORM)
- **DLQ (Dead Letter Queue):** Cola de mensajes fallidos en RabbitMQ
- **p95 (Percentile 95):** El 95% de las requests son más rápidas que este valor

---

**📋 Plan de Pruebas v3.0 — Backend Ticket Service**  
*Actualizado: 25 de Febrero de 2026*
