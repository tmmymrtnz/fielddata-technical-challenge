# Guía de Demo

Esta es la forma más prolija de mostrar el proyecto sin perder control sobre cuándo corre el worker.

## Setup

Corré esto una vez antes de la presentación:

```bash
make demo
```

Qué hace `make demo`:

1. baja cualquier stack anterior
2. levanta PostgreSQL y el webhook mock de WhatsApp
3. corre las migraciones de Alembic
4. seedea un dataset chico y determinístico para demo
5. levanta sólo la API

Importante:

- `make demo` **no** levanta el worker a propósito
- eso te deja controlar el flujo de trigger y delivery
- cuando quieras mostrar el procesamiento, corré `make worker-once`

## Flujo de Demo

Abrí Swagger:

- [http://localhost:8000/docs](http://localhost:8000/docs)

### 1. Mostrar liveness y readiness

Corré:

- `GET /health`
- `GET /ready`

Qué decir:

- `/health` demuestra que el proceso de API está vivo
- `/ready` demuestra que la API puede hablar con la base

Resultado esperado:

- ambos devuelven `{"status":"ok"}`

### 2. Mostrar el scoping por usuario con los campos seedados

Corré:

- `GET /fields?user_id=1`

Qué decir:

- el sistema scopea las lecturas por `user_id`
- el seed ya te deja datos legibles para demo

Resultado esperado:

- campos del usuario `1`
- deberías ver nombres como `Campo Norte` y `Campo Sur`

Usá `field_id=1` para el paso siguiente, salvo que los IDs devueltos sean distintos.

### 3. Crear una alerta manualmente

Corré:

- `POST /alerts`

Payload:

```json
{
  "user_id": 1,
  "field_id": 1,
  "name": "Demo Helada Campo Norte",
  "metric": "temp_min_c",
  "operator": "lte",
  "threshold_value": 0,
  "lookahead_days": 1
}
```

Qué decir:

- las alertas son reglas genéricas sobre métricas de forecast
- esta en particular está chequeando riesgo de helada en el horizonte del día actual

### 4. Mostrar que todavía no existe ninguna notificación

Corré:

- `GET /notifications?user_id=1`

Qué decir:

- la API sólo crea configuración
- el worker es un proceso separado, así que no se evalúa nada hasta que corre

Resultado esperado:

- lista vacía, o por lo menos ninguna notificación asociada a la alerta nueva

### 5. Disparar la evaluación bajo demanda

Corré en otra terminal:

```bash
make worker-once
```

Qué decir:

- este es el worker en background ejecutando un ciclo de evaluación
- evalúa alertas, crea triggers idempotentes y manda deliveries

### 6. Mostrar el historial de notificaciones

Corré:

- `GET /notifications?user_id=1`

Qué decir:

- el ítem devuelto está construido a partir de un snapshot persistido del trigger
- eso preserva el significado histórico aunque después se edite la alerta

Resultado esperado:

- una nueva notificación con el nombre de la alerta
- el estado de delivery debería aparecer como `delivered`

### 7. Mostrar el delivery hacia el downstream mock

Corré en otra terminal:

```bash
docker compose logs --tail=20 mock-whatsapp
```

Qué decir:

- el delivery está mockeado, pero sale por HTTP de verdad
- el worker envió un webhook al servicio downstream

Resultado esperado:

- una línea de log que contenga `Mock WhatsApp delivery`

### 8. Probar idempotencia

Corré de nuevo:

```bash
make worker-once
```

Después llamá:

- `GET /notifications?user_id=1`

Qué decir:

- volver a correr el worker no duplica el mismo evento de negocio
- la idempotencia está garantizada con constraints en la base

Resultado esperado:

- no aparece una notificación duplicada para el mismo trigger

### 9. Mostrar el comportamiento de soft delete

Corré:

- `GET /alerts?user_id=1`
- copiá el `id` de `Demo Helada Campo Norte`
- `DELETE /alerts/{id}?user_id=1`
- `GET /alerts?user_id=1`
- `GET /notifications?user_id=1`

Qué decir:

- borrar una alerta es un soft delete
- la configuración activa desaparece
- el historial de notificaciones se conserva

Resultado esperado:

- la alerta deja de aparecer en `/alerts`
- el historial en `/notifications` sigue estando

## Versión Corta

Si tenés sólo unos minutos, hacelo así:

1. `make demo`
2. `GET /health`
3. `GET /ready`
4. `GET /fields?user_id=1`
5. `POST /alerts`
6. `make worker-once`
7. `GET /notifications?user_id=1`
8. `docker compose logs --tail=20 mock-whatsapp`
9. `make worker-once` de nuevo para mostrar que no duplica

## Puntos Recomendados para Contar

- monolito modular con API y worker separados
- FastAPI async más SQLAlchemy async
- persistencia de forecasts diarios
- alertas basadas en reglas por métrica, operador, umbral y lookahead
- idempotencia garantizada por base de datos
- retries de delivery y seguimiento de estado operativo
- soft delete más snapshots inmutables de trigger
