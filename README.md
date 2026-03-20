# Challenge Técnico de Alertas Climáticas

Challenge técnico backend para un sistema de alertas climáticas construido con FastAPI, SQLAlchemy, PostgreSQL, Alembic y un worker async.

## Qué Resuelve

El sistema permite que los usuarios configuren alertas meteorológicas sobre sus campos, evalúa periódicamente los forecasts persistidos y crea notificaciones cuando se cumple un umbral configurado.

Este repositorio incluye:

- endpoints de API REST
- worker en background para evaluar alertas
- esquema PostgreSQL y migraciones de Alembic
- seed de datos climáticos mockeados
- delivery mockeado de notificaciones por HTTP
- tests unitarios y de integración

La integración con WhatsApp no está implementada a propósito. En su lugar, las notificaciones se envían a un webhook mock que loguea el payload recibido.

## Supuestos y Alcance

Tomé estos supuestos explícitos para mantener la implementación enfocada y con criterio de producción:

- La granularidad del forecast es diaria.
- Los datos climáticos ya fueron ingeridos y están persistidos en la base.
- Para este ejercicio, la ingesta está mockeada con un script de seed.
- Las alertas están modeladas como reglas genéricas sobre métricas persistidas, no como lógica hardcodeada por tipo de evento.
- No hay capa de autenticación; el acceso a la API está scopeado por `user_id`.
- Cada campo pertenece exactamente a un usuario.

Como no hay autenticación real en esta versión, el `user_id` viaja explícitamente en los requests de lectura y escritura para permitir validación de ownership. En una versión productiva, ese `user_id` saldría del contexto de autenticación y no del request.

## Supuestos Adicionales Tomados Durante la Implementación

Además del alcance base del challenge, durante la implementación se tomaron estas decisiones explícitas:

- La evaluación es eventual: crear o editar una alerta no dispara una evaluación sincrónica desde la API; el efecto se ve cuando corre el worker.
- El sistema está pensado para una sola instancia de worker. No intenta resolver coordinación distribuida ni claiming entre múltiples workers.
- Las métricas y umbrales se almacenan como enteros para simplificar comparaciones, constraints y snapshots. Eso prioriza claridad y robustez por sobre precisión decimal fina.
- La semántica temporal relevante del dominio está basada en `forecast_date` diaria, no en timestamps intradía por zona geográfica del campo.
- El único canal de delivery implementado es un webhook HTTP mock. No hay fan-out multicanal ni preferencias por usuario.
- El historial de notificaciones se conserva a través de snapshots; editar o borrar una alerta no reescribe eventos ya disparados.
- Los listados no tienen paginación ni filtros avanzados porque la escala objetivo del challenge es chica y controlada.
- Los campos y forecasts no se gestionan desde la API pública en esta versión; entran por seed/mock de ingesta previa.

Estas decisiones están pensadas para mantener el proyecto defendible y coherente como challenge backend, sin agregar complejidad que no sume señal técnica.

## Decisiones de Diseño Principales

### Monolito Modular con Dos Procesos

El proyecto está implementado como un monolito modular con entrypoints separados para:

- `api`: atiende tráfico HTTP
- `worker`: evalúa alertas periódicamente y entrega notificaciones

Ambos comparten el mismo codebase y el mismo modelo de dominio, pero corren como procesos separados. Eso mantiene a la API responsiva y evita acoplar la latencia de requests con la ejecución batch.
Esta versión asume una sola instancia de worker y no coordina múltiples workers.

### Modelo de Datos Climáticos

Los forecasts se almacenan en una única tabla diaria: `weather_forecasts`.

Métricas soportadas en v1:

- `temp_min_c`
- `temp_max_c`
- `rain_mm`
- `rain_probability_pct`
- `snow_mm`
- `snow_probability_pct`
- `wind_speed_mps`
- `wind_gust_mps`

Saqué `weather_code` a propósito en esta versión para no inventar semánticas de eventos que no eran estrictamente necesarias para el challenge.

### Modelo de Alertas

Las alertas se definen por:

- `field_id`
- `metric`
- `operator`
- `threshold_value`
- `lookahead_days`

Operadores soportados:

- `lt`
- `lte`
- `gt`
- `gte`

`lookahead_days` se configura por alerta y está acotado a `1..30`.

### Reglas de Negocio

- Cada día de forecast se evalúa de manera independiente.
- Una misma alerta puede dispararse una sola vez por `forecast_date`.
- Los valores de métrica en `NULL` no disparan alertas.
- Las alertas tienen soft delete.
- Editar una alerta impacta sólo en ciclos futuros del worker.
- Los triggers existentes no se cancelan si el forecast cambia después.

### Idempotencia

La idempotencia se garantiza a nivel base de datos con:

- `UNIQUE(field_id, forecast_date)` en `weather_forecasts`
- `UNIQUE(alert_id, weather_forecast_id)` en `alert_triggers`

Eso garantiza que volver a correr el worker no genere triggers duplicados para la misma alerta y la misma fila de forecast.

### Separación entre Trigger y Delivery

Separé el disparo de negocio del delivery saliente:

- `alert_triggers`: se cumplió la condición de la alerta
- `notification_deliveries`: el sistema intentó enviar la notificación

Eso mantiene limpia la lógica central de alertas y permite retries sin duplicar eventos de negocio.

## Modelo de Datos

Tablas principales:

- `users`
- `fields`
- `weather_forecasts`
- `alerts`
- `alert_triggers`
- `notification_deliveries`

`alert_triggers` guarda un snapshot de la regla al momento del disparo, así el historial de notificaciones se mantiene estable aunque después se edite la alerta.

## Asincronía y Procesamiento en Background

El worker es asíncrono y corre separado de la API.
La implementación asume un solo proceso worker evaluando alertas y enviando notificaciones.

Cada ciclo:

1. Carga las alertas activas.
2. Busca los forecasts para el horizonte de cada alerta.
3. Evalúa la métrica, el operador y el umbral configurados.
4. Inserta los triggers faltantes de manera idempotente.
5. Crea filas pendientes de delivery.
6. Envía las notificaciones pendientes al webhook mock.
7. Reintenta deliveries fallidos con backoff.

El intervalo por defecto del worker es de `1` minuto y se puede configurar con `--interval-minutes`.
Si un ciclo falla, el worker loguea la excepción y reintenta después de un backoff corto configurable, en lugar de morirse definitivamente.

## Cómo Están Mockeados los Datos Climáticos

El challenge asume que ya existe un job de ingesta climática. Para este ejercicio, esa ingesta está mockeada mediante un comando de seed que inserta:

- `12` usuarios por defecto
- `48` campos por defecto, con varios campos por usuario
- `720` forecasts diarios por defecto
- `144` alertas de ejemplo por defecto

Los primeros usuarios y campos seedados se mantienen legibles para la demo:

- `Alice Farmer`: `Campo Norte`, `Campo Sur`, `Campo Central`, `Campo Oeste`
- `Bob Grower`: `Lote Este`, `Lote Oeste`, `Lote Norte`, `Lote Sur`

Comando de seed:

```bash
python -m app.cli seed-demo --reset
```

También podés escalar el dataset para arriba o para abajo:

```bash
python -m app.cli seed-demo --reset --users 20 --fields-per-user 5 --forecast-days 21
```

## Cómo Correrlo

La forma más simple de reproducir el proyecto es con Docker Compose.

### Requisitos Previos

- Docker
- Docker Compose

### Inicio

```bash
make up
```

Esto:

- levanta PostgreSQL
- levanta el webhook mock de notificaciones
- aplica migraciones de Alembic
- seedea datos de demo
- levanta la API
- levanta el worker

Documentación de la API:

- [http://localhost:8000/docs](http://localhost:8000/docs)

### Comandos Útiles

- `make migrate`
- `make seed`
- `make demo`
- `make worker-once`
- `make test`
- `make test-local`
- `make logs`
- `make down`

## CI/CD

El repositorio incluye CI con GitHub Actions en `.github/workflows/ci.yml`.

Flujo:

- cada pull request corre la suite completa contra PostgreSQL
- los pushes a `main` vuelven a correr los mismos checks
- si los checks pasan en `main`, Render puede deployar automáticamente

Pasos del CI:

- instalar dependencias de Python
- compilar el codebase con `compileall`
- correr `pytest` contra un servicio PostgreSQL
- buildar la imagen Docker para detectar regressions del contenedor

## Deploy en la Nube

El repositorio incluye un Blueprint de Render en `render.yaml`.

Define:

- una base PostgreSQL administrada
- un servicio web para la API
- un worker en background
- un servicio privado para el webhook mock de WhatsApp

Setup recomendado:

1. Subí el repositorio a GitHub.
2. En Render, creá un Blueprint nuevo y apuntalo a este repositorio.
3. Mantené `autoDeployTrigger: checksPass` en los servicios.
4. Abrí un pull request: GitHub Actions corre CI.
5. Mergeá a `main`: GitHub Actions corre de nuevo, y Render deploya sólo si los checks quedan en verde.

Notas:

- la aplicación acepta el connection string estándar de Postgres de Render y lo normaliza a `asyncpg`
- la API corre `alembic upgrade head` como `preDeployCommand`
- el worker y la API resuelven la URL del webhook mock a partir del host/port del servicio privado
- el health check de Render apunta a `/ready`, que verifica conectividad con la base en lugar de chequear sólo que el proceso siga vivo
- este stack usa recursos pagos de Render (`starter` y una instancia chica de Postgres administrado), lo cual está bien para challenge/demo pero conviene decirlo explícitamente

## Resumen de la API

Nota:

- los endpoints usan `user_id` para validar ownership porque el challenge no implementa autenticación real; en una versión productiva, ese dato debería resolverse desde auth y no venir en query params o payloads
- los errores HTTP se devuelven con un formato consistente que incluye `error.code`, `error.message` y `request_id`, para facilitar debugging y trazabilidad

- `GET /health`
- `GET /ready`
- `GET /fields?user_id=1`
- `POST /alerts`
- `GET /alerts?user_id=1`
- `GET /alerts/{id}?user_id=1`
- `PATCH /alerts/{id}?user_id=1`
- `DELETE /alerts/{id}?user_id=1`
- `GET /notifications?user_id=1`

Ejemplo de payload para una alerta:

```json
{
  "user_id": 1,
  "field_id": 1,
  "name": "Helada campo norte",
  "metric": "temp_min_c",
  "operator": "lte",
  "threshold_value": 0,
  "lookahead_days": 5
}
```

## Migraciones

Alembic se usa para versionar el esquema.

Para correr migraciones manualmente:

```bash
make migrate
```

La migración inicial está en:

- `alembic/versions/20260320_0001_initial_schema.py`

## Tests

El repositorio incluye:

- tests unitarios para el evaluador de métricas
- tests de integración que cubren creación de alertas, ejecución del worker, generación de notificaciones y comportamiento de soft delete

Para correr tests:

```bash
make test
```

Para correr `pytest` localmente fuera de Docker, creá una vez un archivo de entorno dedicado para tests:

```bash
cp .env.test.example .env.test
docker compose up -d db
make test-local
```

`make test-local` usa `127.0.0.1:55432` por defecto para no conectarse por accidente a una instancia de PostgreSQL que ya tengas corriendo en tu máquina. Sobrescribí `HOST_POSTGRES_PORT` sólo si necesitás publicar la base en otro puerto.

La suite resuelve la URL de base en este orden:

- `TEST_DATABASE_URL`
- `DATABASE_URL`
- `.env.test`

El nombre de la base tiene que ser exactamente `climate_alerts_test` para que los tests no puedan correr por error contra la base de la app.

La implementación también fue verificada localmente con `pytest` dentro de un virtualenv del proyecto.

## Notas para la Demo

- El delivery de notificaciones está mockeado con un webhook HTTP, no con WhatsApp real.
- El webhook loguea el payload por stdout.
- El comportamiento de retry se puede mostrar seteando `MOCK_WHATSAPP_FAIL_FIRST_DELIVERY=true`.

## Estructura del Repositorio

- `app/`: código de la aplicación
- `alembic/`: migraciones
- `tests/`: tests unitarios y de integración
- `docs/`: notas de implementación

Guion de demo:

- `docs/DEMO_GUIDE.md`

## Consideraciones Futuras

Si este proyecto evolucionara más allá del challenge, las prioridades naturales serían:

### 1. Endurecimiento para producción

- autenticación y autorización reales
- secrets management y configuración por entorno más estricta
- métricas, trazas y dashboards para API y worker
- políticas de restart, alerting y health checks operativos más completas

### 2. Evolución del modelo operativo

- ingesta real de forecasts en lugar de datos seedados
- paginación y filtros en endpoints de lectura
- soporte para más canales de notificación
- rate limiting y controles de abuse en la API

### 3. Escalado y consistencia

- coordinación segura entre múltiples workers si hiciera falta escalar horizontalmente
- semánticas más fuertes de scheduling o dirty-tracking para evitar reevaluación completa en escenarios grandes
- aislamiento más explícito entre estado de negocio y estado operativo del delivery

### 4. Profundización del dominio

- zonas horarias por campo o por usuario
- métricas adicionales o eventos compuestos
- políticas más ricas de deduplicación y supresión de alertas
- reglas más expresivas que una sola métrica por alerta
