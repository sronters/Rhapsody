from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import InMemoryRateLimitMiddleware, RequestContextMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_sentry(settings.sentry_dsn)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.is_non_prod else None,
        redoc_url="/redoc" if settings.is_non_prod else None,
        openapi_url="/openapi.json" if settings.is_non_prod else None,
        lifespan=lifespan,
    )
    app.add_middleware(InMemoryRateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )
    app.include_router(api_router, prefix="/api/v1")
    app.mount("/metrics", make_asgi_app())
    return app


def configure_sentry(sentry_dsn: str | None) -> None:
    if not sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.05)


app = create_app()
