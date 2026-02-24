# USER STORIES Y CRITERIOS DE ACEPTACIÓN
## Backend Ticket Service — API REST

**Versión:** 1.0  
**Fecha:** 24 Febrero 2026  
**Estado:** ✅ Validado y Aprobado

---

## 📋 Contexto de Negocio

Backend Ticket Service es un sistema Django REST Framework con arquitectura DDD/EDA que ya expone una API funcional. Se requiere:

1. **Mejorar profesionalidad de la API**: documentación autodescubrible

Resultado esperado: API lista para producción con documentación y pruebas E2E.

---

## 🎯 Objetivos del Producto

- ✅ API con documentación OpenAPI (Swagger) en `/api/docs/`
- ✅ Tests E2E validando flujos completos con pytest

---

## 📦 Épicas

### **ÉPICA 1: API REST Profesional & Documentada**
Transformar API a nivel producción con documentación autodescubrible y validación E2E.

**Valor:** Devs pueden onboarden sin leer código, API validada con flujos completos.

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

## ✅ VALIDACIÓN INVEST (Resumen)

Todas las historias están validadas INVEST:

| Story | I | N | V | E | S | T | Estado |
|-------|---|---|---|---|---|---|--------|
| STORY-1.1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |
| STORY-1.2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Aprobada |

---

## 🗺 Resumen por Épica

### **ÉPICA 1: API REST Profesional & Documentada (2 historias)**

| Story | Descripción | Esfuerzo | Dependencias |
|-------|-------------|----------|-------------|
| STORY-1.1 | Documentación OpenAPI (drf-spectacular) | 2-3 d | Ninguna |
| STORY-1.2 | Tests E2E (pytest) | 3-4 d | STORY-1.1 |
| **Total ÉPICA 1** | **API validada** | **5-7 días** | **Secuencial** |

### **TOTAL PROYECTO**

- **Total de historias:** 2
- **Esfuerzo estimado:** 5-7 días de desarrollo
- **Timeline realista:** 1-2 semanas (1 developer full-time)
- **Resultado:** API documentada y validada con E2E

---

## 📌 Orden de Ejecución Recomendado

### **Fase 1 (Secuencial, ~1 semana)**
- ✅ STORY-1.1 (OpenAPI) — Backend Dev
- ✅ STORY-1.2 (E2E Tests) — valida STORY-1.1

---

## 🎯 Conclusión

Este documento define 2 historias de usuario enfocadas en asegurar:

1. ✅ **API profesional** con documentación autodescubrible
2. ✅ **Validación completa** mediante tests E2E

**Todas las decisiones han sido validadas por el product owner y son vinculantes para implementación.**

---

**Aprobado por:** Backend Ticket Service Team  
**Fecha de aprobación:** 24 Febrero 2026  
**Versión:** 1.0 (Final)
