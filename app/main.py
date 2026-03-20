from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.core.config import get_settings
from app.core.errors import register_exception_handlers, request_context_middleware
from app.core.logging import configure_logging
from app.db.session import check_database_connection, dispose_engine
from app.modules.alerts.api import router as alerts_router
from app.modules.fields.api import router as fields_router
from app.modules.notifications.delivery import close_delivery_clients
from app.modules.notifications.api import router as notifications_router

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_delivery_clients()
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)
app.include_router(fields_router)
app.include_router(alerts_router)
app.include_router(notifications_router)


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    try:
        await check_database_connection()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable") from exc
    return {"status": "ok"}
