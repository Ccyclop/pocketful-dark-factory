"""Application factory."""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from . import errors
from .config import Settings, load_settings
from .db import Database
from .responses import JsonResponse
from .routers import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_path)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Runs before uvicorn accepts connections, so /health is only served once
        # the data store is ready.
        db.initialize()
        yield

    app = FastAPI(
        lifespan=lifespan,
        default_response_class=JsonResponse,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    app.state.db = db
    app.state.settings = settings
    errors.install(app)
    app.include_router(health.router)
    return app
