from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from backend.api.auth_routes import router as auth_router
from backend.api.credential_routes import router as credential_router
from backend.api.health_routes import router as health_router
from backend.api.metrics_routes import router as metrics_router
from backend.api.project_routes import router as project_router
from backend.api.run_routes import router as run_router
from backend.api.run_routes import websocket_router
from backend.api.webhook_routes import router as webhook_router
from backend.api.workflow_routes import router as workflow_router
from backend.config import get_settings
from backend.lifecycle import runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_runtime_secrets()
    try:
        await runtime.start()
    except SQLAlchemyError:
        if settings.is_production:
            raise
    try:
        yield
    finally:
        await runtime.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kyron Workflow Engine",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(project_router, prefix="/api")
    app.include_router(credential_router, prefix="/api")
    app.include_router(workflow_router, prefix="/api")
    app.include_router(run_router, prefix="/api")
    app.include_router(webhook_router, prefix="/api")
    app.include_router(websocket_router, prefix="/api")
    return app


app = create_app()
