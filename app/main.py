from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.alerts.api import router as alerts_router
from app.modules.fields.api import router as fields_router
from app.modules.notifications.api import router as notifications_router

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name)
app.include_router(fields_router)
app.include_router(alerts_router)
app.include_router(notifications_router)


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}

