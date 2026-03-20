from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.alerts.models import Alert, AlertMetric, AlertOperator


def _api_datetime(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _assert_error_shape(response, *, status_code: int, code: str, message: str) -> None:
    body = response.json()

    assert response.status_code == status_code
    assert response.headers["X-Request-ID"]
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["error"]["code"] == code
    assert body["error"]["message"] == message


async def test_healthcheck_returns_ok(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


async def test_readiness_returns_ok_when_database_check_succeeds(client, monkeypatch) -> None:
    async def fake_check_database_connection() -> None:
        return None

    monkeypatch.setattr("app.main.check_database_connection", fake_check_database_connection)

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_returns_503_when_database_check_fails(client, monkeypatch) -> None:
    async def fake_check_database_connection() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.main.check_database_connection", fake_check_database_connection)

    response = await client.get("/ready")

    _assert_error_shape(
        response,
        status_code=503,
        code="service_unavailable",
        message="database unavailable",
    )


async def test_get_fields_filters_by_user_id(client, factory) -> None:
    user_one = await factory.user(name="Alice")
    user_two = await factory.user(name="Bob")
    field_one = await factory.field(user=user_one, name="Campo Norte")
    await factory.field(user=user_two, name="Lote Este")

    response = await client.get(f"/fields?user_id={user_one.id}")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": field_one.id,
            "user_id": user_one.id,
            "name": "Campo Norte",
            "created_at": _api_datetime(field_one.created_at),
            "updated_at": _api_datetime(field_one.updated_at),
        }
    ]


async def test_post_and_get_alerts_persist_and_filter_by_user_id(client, factory, session_factory) -> None:
    user_one = await factory.user(name="Alice")
    user_two = await factory.user(name="Bob")
    field_one = await factory.field(user=user_one, name="Campo Norte")
    field_two = await factory.field(user=user_two, name="Lote Este")

    payload = {
        "user_id": user_one.id,
        "field_id": field_one.id,
        "name": "Helada Campo Norte",
        "metric": "temp_min_c",
        "operator": "lte",
        "threshold_value": 0,
        "lookahead_days": 3,
    }
    create_response = await client.post("/alerts", json=payload)
    second_response = await client.post(
        "/alerts",
        json={
            "user_id": user_two.id,
            "field_id": field_two.id,
            "name": "Lluvia Lote Este",
            "metric": "rain_mm",
            "operator": "gte",
            "threshold_value": 20,
            "lookahead_days": 5,
        },
    )

    assert create_response.status_code == 201
    assert second_response.status_code == 201

    alert_id = create_response.json()["id"]
    async with session_factory() as session:
        created_alert = await session.get(Alert, alert_id)

    assert created_alert is not None
    assert created_alert.metric == AlertMetric.TEMP_MIN_C
    assert created_alert.operator == AlertOperator.LTE
    assert created_alert.threshold_value == 0
    assert created_alert.lookahead_days == 3

    list_response = await client.get(f"/alerts?user_id={user_one.id}")

    assert list_response.status_code == 200
    assert [alert["name"] for alert in list_response.json()] == ["Helada Campo Norte"]


async def test_get_alert_by_id_returns_owned_alert_and_hides_foreign_one(client, factory) -> None:
    owner = await factory.user(name="Alice")
    other_user = await factory.user(name="Bob")
    owner_field = await factory.field(user=owner, name="Campo Norte")
    alert = await factory.alert(
        field=owner_field,
        name="Helada Campo Norte",
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=3,
    )

    response = await client.get(f"/alerts/{alert.id}?user_id={owner.id}")
    foreign_response = await client.get(f"/alerts/{alert.id}?user_id={other_user.id}")

    assert response.status_code == 200
    assert response.json()["id"] == alert.id
    assert response.json()["user_id"] == owner.id
    assert response.json()["name"] == "Helada Campo Norte"
    _assert_error_shape(
        foreign_response,
        status_code=404,
        code="not_found",
        message="Alert not found for user",
    )


async def test_post_alert_validates_payload_and_field_ownership(client, factory) -> None:
    user = await factory.user(name="Alice")
    other_user = await factory.user(name="Bob")
    owned_field = await factory.field(user=user, name="Campo Norte")
    foreign_field = await factory.field(user=other_user, name="Lote Este")

    invalid_payload_response = await client.post(
        "/alerts",
        json={
            "user_id": user.id,
            "field_id": owned_field.id,
            "name": "",
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "lookahead_days": 0,
        },
    )
    foreign_field_response = await client.post(
        "/alerts",
        json={
            "user_id": user.id,
            "field_id": foreign_field.id,
            "name": "Invalid owner",
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "lookahead_days": 2,
        },
    )

    _assert_error_shape(
        invalid_payload_response,
        status_code=422,
        code="validation_error",
        message="La request no pasó la validación",
    )
    assert invalid_payload_response.json()["error"]["details"]
    _assert_error_shape(
        foreign_field_response,
        status_code=404,
        code="not_found",
        message="Field not found for user",
    )


async def test_patch_alert_updates_fields_and_resets_last_evaluated_at(client, factory, session_factory, frozen_time) -> None:
    user = await factory.user(name="Alice")
    field = await factory.field(user=user, name="Campo Norte")
    alert = await factory.alert(
        field=field,
        name="Helada",
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
        last_evaluated_at=frozen_time(),
    )

    response = await client.patch(
        f"/alerts/{alert.id}?user_id={user.id}",
        json={
            "name": "Helada ajustada",
            "operator": "lt",
            "threshold_value": -2,
            "lookahead_days": 4,
            "is_active": False,
        },
    )
    wrong_owner_response = await client.patch(
        f"/alerts/{alert.id}?user_id={user.id + 999}",
        json={"name": "Nope"},
    )

    assert response.status_code == 200
    _assert_error_shape(
        wrong_owner_response,
        status_code=404,
        code="not_found",
        message="Alert not found for user",
    )

    async with session_factory() as session:
        updated_alert = await session.get(Alert, alert.id)

    assert updated_alert is not None
    assert updated_alert.name == "Helada ajustada"
    assert updated_alert.operator == AlertOperator.LT
    assert updated_alert.threshold_value == -2
    assert updated_alert.lookahead_days == 4
    assert updated_alert.is_active is False
    assert updated_alert.last_evaluated_at is None


async def test_delete_alert_soft_deletes_and_hides_from_list(client, factory, session_factory) -> None:
    user = await factory.user(name="Alice")
    field = await factory.field(user=user, name="Campo Norte")
    alert = await factory.alert(field=field, name="Helada")

    delete_response = await client.delete(f"/alerts/{alert.id}?user_id={user.id}")
    list_response = await client.get(f"/alerts?user_id={user.id}")
    update_deleted_response = await client.patch(f"/alerts/{alert.id}?user_id={user.id}", json={"name": "Nope"})

    assert delete_response.status_code == 204
    assert list_response.status_code == 200
    assert list_response.json() == []
    _assert_error_shape(
        update_deleted_response,
        status_code=404,
        code="not_found",
        message="Alert not found for user",
    )

    async with session_factory() as session:
        deleted_alert = await session.execute(select(Alert).where(Alert.id == alert.id))
        stored_alert = deleted_alert.scalar_one()

    assert stored_alert.deleted_at is not None
    assert stored_alert.is_active is False


async def test_global_handler_returns_500_for_unhandled_application_errors(client, factory, monkeypatch) -> None:
    user = await factory.user(name="Alice")
    field = await factory.field(user=user, name="Campo Norte")

    async def broken_require_field_for_user(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.modules.alerts.api.require_field_for_user", broken_require_field_for_user)

    response = await client.post(
        "/alerts",
        json={
            "user_id": user.id,
            "field_id": field.id,
            "name": "Helada Campo Norte",
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "lookahead_days": 2,
        },
    )

    _assert_error_shape(
        response,
        status_code=500,
        code="internal_error",
        message="Ocurrió un error interno",
    )


async def test_global_handler_returns_409_for_integrity_errors(client, factory, monkeypatch) -> None:
    user = await factory.user(name="Alice")
    field = await factory.field(user=user, name="Campo Norte")

    async def broken_commit(self):  # noqa: ARG001
        raise IntegrityError("INSERT INTO alerts", {}, Exception("duplicate"))

    monkeypatch.setattr("app.modules.alerts.api.AsyncSession.commit", broken_commit)

    response = await client.post(
        "/alerts",
        json={
            "user_id": user.id,
            "field_id": field.id,
            "name": "Helada Campo Norte",
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "lookahead_days": 2,
        },
    )

    _assert_error_shape(
        response,
        status_code=409,
        code="integrity_error",
        message="La operación viola una restricción de integridad de datos",
    )
