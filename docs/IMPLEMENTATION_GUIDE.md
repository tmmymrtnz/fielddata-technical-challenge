# Guía de Implementación

Este documento resume la forma esperada de la implementación del challenge, para que el proyecto se pueda construir o extender sin tener que rediseñarlo desde cero.

## Objetivo

Implementar un servicio backend que permita a los usuarios definir alertas meteorológicas sobre sus campos, evaluar periódicamente forecasts diarios persistidos y producir triggers de notificación idempotentes con delivery reintentable hacia un webhook mock.

## Alcance

- Los forecasts diarios ya existen en la base de datos, ya sea por datos seedados o por un job externo de ingesta.
- Las alertas se configuran por campo.
- Cada alerta observa una métrica, un operador y un umbral.
- La evaluación del worker es periódica y asíncrona.
- La creación de triggers tiene que ser idempotente.
- El delivery está mockeado con un webhook HTTP.
- No hay autenticación. Todas las lecturas y escrituras de la API están scopeadas por `user_id`.

## Stack Técnico

- FastAPI para las APIs HTTP
- ORM async de SQLAlchemy para acceso a datos
- PostgreSQL como storage orientado a producción
- Alembic para migraciones versionadas
- HTTPX para el delivery del webhook
- Pytest para tests
- Docker Compose para reproducibilidad

## Arquitectura

- `app/main.py`: entrypoint de la API
- `app/worker/main.py`: entrypoint del worker
- `app/mock_whatsapp/app.py`: servicio downstream mock
- `app/cli.py`: comando de seed

El worker está separado de manera intencional del proceso de API. Eso aísla la ejecución batch de la latencia HTTP y evita meter la lógica de scheduling dentro del lifecycle de la app web.
La implementación actual asume una sola instancia de worker. El escalado horizontal de workers queda fuera de alcance en esta versión.

## Decisiones de Modelado

### Forecasts

- La granularidad es diaria.
- `weather_forecasts` tiene una fila por `field_id + forecast_date`.
- Los valores del forecast se almacenan en columnas normalizadas, no en estructuras anidadas específicas del proveedor.

### Alertas

- Las alertas son reglas genéricas, no tipos de evento hardcodeados.
- Métricas soportadas en v1:
  - `temp_min_c`
  - `temp_max_c`
  - `rain_mm`
  - `rain_probability_pct`
  - `snow_mm`
  - `snow_probability_pct`
  - `wind_speed_mps`
  - `wind_gust_mps`
- Operadores soportados en v1:
  - `lt`
  - `lte`
  - `gt`
  - `gte`
- `lookahead_days` es un entero por alerta acotado a `1..30`.

### Semántica de Alertas

- El worker evalúa cada `forecast_date` de manera independiente.
- `lookahead_days` significa “evaluar hoy más los próximos `lookahead_days - 1` forecasts diarios”.
- Las métricas en `NULL` no disparan alertas.
- Las actualizaciones de forecast pueden crear nuevos triggers en ciclos futuros del worker.
- Los triggers existentes nunca se cancelan de manera retroactiva.
- Editar una alerta impacta sólo en evaluaciones futuras.

### Separación entre Trigger y Delivery

- `alert_triggers` almacena el evento de negocio “esta alerta disparó para este forecast”.
- `notification_deliveries` almacena intentos de delivery y estado operativo de retries.
- Esta separación mantiene la creación idempotente de triggers aislada de los problemas operativos del delivery.

## Ciclo del Worker

Cada ciclo del worker hace dos cosas:

1. Evalúa alertas activas contra los forecasts dentro de su horizonte de lookahead.
2. Entrega notificaciones pendientes o reintentables al webhook mock.

Si un ciclo falla, el worker loguea la excepción y reintenta después de un backoff corto configurable, en lugar de terminar el proceso.

Por qué se reevalúan todas las alertas activas en cada ciclo:

- las ventanas diarias se mueven con el paso del tiempo,
- las alertas editadas deberían impactar en el próximo ciclo,
- los forecasts actualizados deberían tomarse sin orchestration adicional,
- la escala del challenge no justifica un scheduler más complejo basado en dirty flags.

## Retries de Delivery

- máximo de retries por defecto: `3`
- minutos de backoff por defecto: `1,5,15`
- el delivery HTTP saliente reutiliza un cliente async dentro del event loop del worker, en lugar de crear un cliente nuevo por notificación
- transiciones de `notification_deliveries.status`:
  - `pending`
  - `retrying`
  - `delivered`
  - `failed`

## Endpoints de Salud

- `GET /health` es un chequeo de liveness del proceso de API
- `GET /ready` verifica conectividad con la base y es un mejor target para health checks de plataforma

## Reproducibilidad

Flujo recomendado para una demo:

1. `make up`
2. Abrí [http://localhost:8000/docs](http://localhost:8000/docs)
3. Creá o editá una alerta
4. Corré `make worker-once` si querés una demostración inmediata
5. Mirá `GET /notifications?user_id=...`
6. Mirá los logs del webhook con `make logs`

## Orden de Implementación Sugerido

1. Scaffold base del proyecto y settings
2. Modelos de SQLAlchemy y migración de Alembic
3. CLI de seed
4. Tests unitarios del evaluador de alertas
5. API de alertas
6. Evaluación del worker y creación idempotente de triggers
7. Webhook mock y retries de delivery
8. API de notificaciones
9. Pulido de Docker Compose, Makefile y README
