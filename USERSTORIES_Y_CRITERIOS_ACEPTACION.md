# USER STORIES Y CRITERIOS DE ACEPTACIÓN
## Backend Ticket Service — API REST

**Versión:** 1.0  
**Fecha:** 24 Febrero 2026  
**Estado:** ✅ Validado y Aprobado

---

## 📋 Contexto de Negocio

Backend Ticket Service es un sistema Django REST Framework con arquitectura DDD/EDA que ya expone una API funcional. Se requiere:

1. **Mejorar profesionalidad de la API**: documentación autodescubrible y validación E2E
2. **Reforzar integridad arquitectónica DDD/EDA**: cerrar brechas que permiten bypass del dominio
3. **Corregir semántica HTTP**: 404 vs 400, manejo genérico de errores 500

Resultado esperado: API lista para producción con documentación, pruebas E2E, y arquitectura DDD sin compromisos.

---

## 🎯 Objetivos del Producto

- ✅ API con documentación OpenAPI (Swagger) en `/api/docs/`
- ✅ Tests E2E validando flujos completos con pytest
- ✅ Arquitectura DDD pura: todos los cambios pasan por use cases
- ✅ Semántica HTTP correcta: 404 para recursos no encontrados, 400 para errores de cliente
- ✅ Resiliencia: manejo genérico de excepciones inesperadas (500)

---

## 📦 Épicas

### **ÉPICA 1: API REST Profesional & Documentada**
Transformar API a nivel producción con documentación autodescubrible y validación E2E.

**Valor:** Devs pueden onboarden sin leer código, API validada con flujos completos.

### **ÉPICA 2: Refactoring Arquitectónico DDD/EDA**
Cerrar brechas arquitectónicas que permiten bypass del dominio, corregir semántica HTTP y reforzar resiliencia.

**Valor:** Garantiza que toda operación pasa por reglas de dominio, genera eventos, y brinda experiencia HTTP predecible y segura.

---

# 📝 HISTORIAS DE USUARIO

## ÉPICA 1: API REST Profesional & Documentada

---

## STORY-1.1 — Documentación OpenAPI/Swagger autodescubrible

**Como** desarrollador consumidor de la API  
**quiero** acceder a `/api/docs/` y ver documentación interactiva automática  
**para** explorar endpoints sin leer código, probar requests en tiempo real

### Criterios de Aceptación (Gherkin)

```gherkin
@epic:API-REST-PRO @story:STORY-1.1 @priority:alta @risk:bajo
Feature: Documentación OpenAPI/Swagger autodescubrible
  Como desarrollador consumidor de la API
  Quiero acceder a documentación interactiva Swagger/Redoc
  Para explorar endpoints sin leer código

  Scenario: Acceder a Swagger UI en /api/docs/
    Given que el servidor está corriendo en http://localhost:8000
    When accedo a GET /api/docs/
    Then recibo status 200
    And la respuesta contiene HTML con interfaz Swagger UI
    And puedo ver todos los endpoints listos: GET/POST /api/v1/tickets/, POST /api/v1/tickets/{id}/change_status/, etc.

  Scenario: Probar endpoint directamente desde Swagger
    Given estoy en la interfaz Swagger UI en /api/docs/
    When hago click en "Try it out" en POST /api/v1/tickets/
    And ingreso {"title": "Bug", "description": "Test", "user_id": "user1"}
    And presiono "Execute"
    Then recibo response 201 Created
    And veo el ticket creado con id, created_at, estado OPEN

  Scenario: Acceso a documentación OpenAPI en JSON
    Given que el servidor está corriendo
    When accedo a GET /api/schema/
    Then recibo status 200 con Content-Type: application/json
    And la respuesta contiene especificación OpenAPI 3.0 completa
    And todos los endpoints están documentados con params, ejemplos, códigos de respuesta
```

### Notas
- **Valor de negocio:** Onboarding de devs externos → reducción de tickets de "¿cómo uso la API?"
- **Decisión:** Usar `drf-spectacular` (librería DRF, estándar moderno)
- **Supuestos confirmados:** `drf-spectacular` está disponible en requirements
- **Dependencias:** Ninguna

---

## STORY-1.2 — Tests E2E validando flujos completos (pytest)

**Como** QA  
**quiero** ejecutar tests que validen flujos completos (crear → actualizar → cerrar ticket)  
**para** garantizar que toda la cadena funciona antes de producción

### Criterios de Aceptación (Gherkin)

```gherkin
@epic:API-REST-PRO @story:STORY-1.2 @priority:alta @risk:bajo
Feature: Tests E2E de flujos completos (pytest)
  Como QA
  Quiero tests E2E que validen flujos del usuario
  Para garantizar integración completa

  Scenario: Flujo completo: Crear → Cambiar estado → Cerrar ticket
    Given que tengo credenciales válidas
    When creo un ticket con POST /api/v1/tickets/:
      | title | Bug crítico |
      | description | Sistema no inicia |
      | user_id | user1 |
    Then recibo status 201 con id=1, status=OPEN

    When cambio estado a IN_PROGRESS con PATCH /api/v1/tickets/1/change_status/:
      | status | IN_PROGRESS |
    Then recibo status 200 con status=IN_PROGRESS

    When cambio state a CLOSED con PATCH /api/v1/tickets/1/change_status/:
      | status | CLOSED |
    Then recibo status 200 con status=CLOSED

  Scenario: Flujo con prioridad y respuestas
    When creo ticket y lo cambio a priority Medium con PATCH /api/v1/tickets/1/change_priority/:
      | priority | Medium |
      | priority_justification | Cliente importante |
    Then recibo status 200 con priority=Medium

    When agrego una respuesta con POST /api/v1/tickets/1/add_response/:
      | response_text | El equipo está investigando |
    Then recibo status 201
    And GET /api/v1/tickets/1/ incluye la respuesta

  Scenario: Validación de errores en flujo
    Given que creo un ticket en OPEN
    When intento cambiar estado inversamente (CLOSED → OPEN) con PATCH /api/v1/tickets/1/change_status/:
      | status | OPEN |
    Then recibo status 400
    And el error es: {"detail": "No se puede cambiar ticket CLOSED a OPEN"}

  Scenario: E2E con 500+ tickets (performance)
    Given existen 500 tickets en BD
    When hago GET /api/v1/tickets/
    Then recibo respuesta en <500ms
    And puedo filtrar sin timeouts
```

### Notas
- **Valor de negocio:** Confianza pre-deployment, detección de regressions, documentación viva
- **Decisión confirmada:** Usar pytest + fixtures + librería `requests`
- **Supuestos confirmados:** Tests en `tickets/tests/integration/test_e2e.py`
- **Dependencias:** STORY-1.1 debe estar completa

---

## ÉPICA 2: Refactoring Arquitectónico DDD/EDA

---

## US-001 — Deshabilitar métodos PUT/PATCH/DELETE heredados de ModelViewSet

**Como** desarrollador (mantenedor de arquitectura)  
**quiero** que los métodos `update`, `partial_update` y `destroy` heredados de `ModelViewSet` estén deshabilitados  
**para** forzar que todo cambio en tickets pase por use cases y publique eventos de dominio

### Criterios de Aceptación (Gherkin)

```gherkin
@epic:integridad-ddd @story:us-001 @priority:alta @risk:alto
Feature: Deshabilitar métodos CRUD genéricos heredados
  Como desarrollador
  Quiero que no existan endpoints genéricos PUT/PATCH/DELETE que bypaseen use cases
  Para asegurar que toda operación pasa por reglas de dominio y genera eventos

  Scenario: Intento PUT genérico devuelve 405
    Given un ticket con id 1 existe en la base de datos
    When se envía una solicitud PUT a /api/tickets/1/
    Then la respuesta es 405 Method Not Allowed
    And el ticket NO ha sido modificado en la base de datos

  Scenario: Intento PATCH genérico devuelve 405
    Given un ticket con id 1 existe en la base de datos
    When se envía una solicitud PATCH a /api/tickets/1/
    Then la respuesta es 405 Method Not Allowed
    And el ticket NO ha sido modificado en la base de datos

  Scenario: Intento DELETE genérico devuelve 405
    Given un ticket con id 1 existe en la base de datos
    When se envía una solicitud DELETE a /api/tickets/1/
    Then la respuesta es 405 Method Not Allowed
    And el ticket se mantiene intacto en la base de datos

  Scenario: Cambio de estado vía endpoint custom /status/ sigue funcionando
    Given un ticket con id 1 en estado OPEN existe
    When se envía PATCH a /api/tickets/1/status/ con {"status": "IN_PROGRESS"}
    Then la respuesta es 200 OK
    And el ticket tiene status IN_PROGRESS
    And se publicó evento TicketStatusChanged

  Scenario: Cambio de prioridad vía endpoint custom /priority/ sigue funcionando
    Given un ticket con id 1 existe
    And el solicitante tiene rol Administrador
    When se envía PATCH a /api/tickets/1/priority/ con {"priority": "High", "justification": "Urgente"}
    Then la respuesta es 200 OK
    And el ticket tiene priority High
    And se publicó evento TicketPriorityChanged

  Scenario: Creación de respuesta vía endpoint custom /responses/ sigue funcionando
    Given un ticket con id 1 existe
    And el solicitante tiene rol ADMIN
    When se envía POST a /api/tickets/1/responses/ con {"text": "Resuelto", "admin_id": "admin1"}
    Then la respuesta es 201 Created
    And la respuesta fue creada
    And se publicó evento TicketResponseAdded
```

### Notas
- **Valor de negocio:** Refuerza la arquitectura DDD e imposibilita modificar el dominio sin pasar por reglas de negocio explícitas
- **Supuestos confirmados:** Solo existen 3 endpoints custom seguros: `change_status`, `change_priority`, `responses` (todos usan use cases)
- **Dependencias:** Ninguna

---

## US-002 — Retornar 404 cuando ticket no existe (en lugar de 400)

**Como** cliente de la API (consumidor de REST)  
**quiero** que reciba 404 Not Found cuando intente operar sobre un ticket inexistente  
**para** diferenciar claramente entre "recurso no existe" y "datos inválidos"

### Criterios de Aceptación (Gherkin)

```gherkin
@epic:semantica-http @story:us-002 @priority:alta @risk:medio
Feature: Retornar 404 cuando el ticket no existe
  Como cliente de la API
  Quiero recibir 404 Not Found cuando un recurso no existe
  Para distinguir entre "recurso inexistente" y "solicitud mal formada"

  Scenario: Cambiar estado de ticket inexistente devuelve 404
    Given un ticket con id 999 NO existe
    When se envía PATCH a /api/tickets/999/status/ con {"status": "CLOSED"}
    Then la respuesta es 404 Not Found
    And el cuerpo es {"error": "Ticket 999 no encontrado"}

  Scenario: Cambiar prioridad de ticket inexistente devuelve 404
    Given un ticket con id 999 NO existe
    When se envía PATCH a /api/tickets/999/priority/ con {"priority": "High"}
    Then la respuesta es 404 Not Found
    And el cuerpo es {"error": "Ticket 999 no encontrado"}

  Scenario: Agregar respuesta a ticket inexistente devuelve 404
    Given un ticket con id 999 NO existe
    And el solicitante es administrador
    When se envía POST a /api/tickets/999/responses/ con {"text": "Prueba", "admin_id": "admin1"}
    Then la respuesta es 404 Not Found
    And la respuesta NO fue creada

  Scenario: Campo 'status' ausente sigue devolviendo 400
    Given un ticket con id 1 existe
    When se envía PATCH a /api/tickets/1/status/ SIN campo status
    Then la respuesta es 400 Bad Request
    And el cuerpo es {"error": "El campo 'status' es requerido"}

  Scenario: Estado inválido sigue devolviendo 400
    Given un ticket con id 1 existe
    When se envía PATCH a /api/tickets/1/status/ con {"status": "INVALID_STATE"}
    Then la respuesta es 400 Bad Request
    And el cuerpo contiene un mensaje de error sobre estado inválido

  Scenario: Campo 'priority' ausente sigue devolviendo 400
    Given un ticket con id 1 existe
    When se envía PATCH a /api/tickets/1/priority/ SIN campo priority
    Then la respuesta es 400 Bad Request
    And el cuerpo es {"error": "El campo 'priority' es requerido"}

  Scenario: Ticket cerrado en change_status sigue devolviendo 400
    Given un ticket con id 1 existe y está CLOSED
    When se envía PATCH a /api/tickets/1/status/ con {"status": "IN_PROGRESS"}
    Then la respuesta es 400 Bad Request
    And el cuerpo contiene error sobre ticket cerrado

  Scenario: Usuario no administrador intenta responder devuelve 403
    Given un ticket con id 1 existe
    And el solicitante NO tiene rol ADMIN
    When se envía POST a /api/tickets/1/responses/ con {"text": "Respuesta", "admin_id": "admin1"}
    Then la respuesta es 403 Forbidden
```

### Notas
- **Valor de negocio:** Cumple con especificación HTTP/REST, mejora experiencia de cliente y facilita debugging
- **Supuestos confirmados:** `ValueError` en use cases cuando no encuentra ticket → debe capturarse y convertir a 404. `Ticket.DoesNotExist` en `_create_response` actualmente devuelve 400 → cambiar a 404
- **Dependencias:** Ninguna

---

## US-003 — Agregar manejo genérico de errores 500 en endpoints custom

**Como** operador de API (SRE/DevOps)  
**quiero** que excepciones inesperadas devuelvan 500 con mensaje genérico  
**para** evitar exposiciones de información interna y garantizar resiliencia

### Criterios de Aceptación (Gherkin)

```gherkin
@epic:resiliencia-errores @story:us-003 @priority:media @risk:medio
Feature: Manejar excepciones inesperadas con 500 genérico
  Como operador
  Quiero que excepciones no previstas devuelvan 500 genérico
  Para mantener seguridad (sin exposición de stacktraces internas) y resiliencia

  Background:
    Given el endpoint PATCH /api/tickets/{id}/status/ existe
    And el endpoint PATCH /api/tickets/{id}/priority/ existe

  Scenario: Excepción inesperada en change_status devuelve 500
    Given un ticket con id 1 existe
    And ocurre una excepción inesperada en el repositorio (conexión DB perdida)
    When se envía PATCH a /api/tickets/1/status/ con {"status": "IN_PROGRESS"}
    Then la respuesta es 500 Internal Server Error
    And el cuerpo es {"error": "Error interno del servidor"}
    And NO aparece stacktrace en la respuesta

  Scenario: Excepción inesperada en change_priority devuelve 500
    Given un ticket con id 1 existe
    And ocurre una excepción inesperada (error en event publisher, timeout, etc.)
    When se envía PATCH a /api/tickets/1/priority/ con {"priority": "High"}
    Then la respuesta es 500 Internal Server Error
    And el cuerpo es {"error": "Error interno del servidor"}
    And NO aparece stacktrace en la respuesta

  Scenario: ValueError previsto en change_status sigue siendo 400
    Given un ticket con id 1 existe
    When se envía PATCH a /api/tickets/1/status/ con {"status": "INVALID_STATE"}
    Then la respuesta es 400 Bad Request
    And el cuerpo contiene error descriptivo sobre estado inválido

  Scenario: TicketAlreadyClosed en change_status sigue siendo 400
    Given un ticket con id 1 está CLOSED
    When se envía PATCH a /api/tickets/1/status/ con {"status": "IN_PROGRESS"}
    Then la respuesta es 400 Bad Request
    And el cuerpo contiene error sobre ticket cerrado

  Scenario: Ausencia de campo requerido sigue siendo 400
    Given un ticket con id 1 existe
    When se envía PATCH a /api/tickets/1/status/ SIN campo status
    Then la respuesta es 400 Bad Request
    And el cuerpo es {"error": "El campo 'status' es requerido"}

  Scenario: Patrón my_tickets (modelo establecido) tiene 500
    Given el endpoint GET /api/tickets/my-tickets/{user_id}/ existe
    And ocurre una excepción inesperada
    When se accede al endpoint
    Then la respuesta es 500 Internal Server Error

  Scenario: InvalidPriorityTransition en change_priority sigue siendo 400
    Given un ticket con id 1 existe
    And el solicitante es Administrador
    When intenta una transición de prioridad no válida
    Then la respuesta es 400 Bad Request

  Scenario: PermissionDenied en change_priority sigue siendo 403
    Given un ticket con id 1 existe
    And el solicitante NO tiene rol Administrador
    When se envía PATCH a /api/tickets/1/priority/ con {"priority": "High"}
    Then la respuesta es 403 Forbidden
```

### Notas
- **Valor de negocio:** Mejora seguridad (sin exposición de detalles internos), resiliencia y experiencia de cliente (errores predecibles)
- **Supuestos confirmados:** `change_status` carece de `except Exception`. `change_priority` carece de `except Exception`. `my_tickets` implementa el modelo correcto con captura genérica
- **Dependencias:** Implementar después de US-001 y US-002 para claridad lógica, pero técnicamente independiente

---

## ✅ VALIDACIÓN INVEST (Resumen)

Todas las historias están validadas INVEST:

| Story | I | N | V | E | S | T | Estado |
|-------|---|---|---|---|---|---|--------|
| STORY-1.1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |
| STORY-1.2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |
| US-001 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |
| US-002 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |
| US-003 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |

---

## 🗺 Resumen por Épica

### **ÉPICA 1: API REST Profesional & Documentada (2 historias)**

| Story | Descripción | Esfuerzo | Dependencias |
|-------|-------------|----------|-------------|
| STORY-1.1 | Documentación OpenAPI (drf-spectacular) | 2-3 d | Ninguna |
| STORY-1.2 | Tests E2E (pytest) | 3-4 d | STORY-1.1 |
| **Total ÉPICA 1** | **API validada** | **5-7 días** | **Secuencial** |

### **ÉPICA 2: Refactoring Arquitectónico DDD/EDA (3 historias)**

| Story | Descripción | Esfuerzo | Dependencias |
|-------|-------------|----------|-------------|
| US-001 | Deshabilitar PUT/PATCH/DELETE heredados | 0.5-1 d | Ninguna |
| US-002 | Retornar 404 cuando ticket no existe | 1-1.5 d | Ninguna |
| US-003 | Manejo genérico de errores 500 | 0.5-1 d | US-001, US-002 |
| **Total ÉPICA 2** | **Integridad DDD/EDA** | **2-3.5 días** | **Secuencial** |

### **TOTAL PROYECTO**

- **Total de historias:** 5 (2 funcionales + 3 arquitectónicas)
- **Esfuerzo estimado:** 7-10.5 días de desarrollo
- **Timeline realista:** 2-3 semanas (1 developer full-time)
- **Resultado:** API documentada, validada con E2E, y con arquitectura DDD reforzada

---

## 📌 Orden de Ejecución Recomendado

### **Fase 1: API Profesional (~1 semana)**
- ✅ STORY-1.1 (OpenAPI) — Backend Dev
- ✅ STORY-1.2 (E2E Tests) — valida STORY-1.1

### **Fase 2: Refactoring Arquitectónico DDD/EDA (~3-4 días)**
- ✅ US-001 (Deshabilitar PUT/PATCH/DELETE) — Refuerza arquitectura DDD
- ✅ US-002 (Retornar 404 correctamente) — Semántica HTTP
- ✅ US-003 (Manejo de errores 500) — Resiliencia y seguridad

---

## 🎯 Conclusión

Este documento define 5 historias de usuario enfocadas en asegurar:

1. ✅ **API profesional** con documentación autodescubrible (OpenAPI/Swagger)
2. ✅ **Validación completa** mediante tests E2E
3. ✅ **Integridad arquitectónica DDD/EDA** sin bypasses al dominio
4. ✅ **Semántica HTTP correcta** (404 vs 400)
5. ✅ **Resiliencia y seguridad** con manejo genérico de errores 500

**Todas las decisiones han sido validadas por el product owner y son vinculantes para implementación.**

---

**Aprobado por:** Backend Ticket Service Team  
**Fecha de aprobación:** 24 Febrero 2026  
**Versión:** 1.0 (Final)
