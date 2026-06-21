from __future__ import annotations

import uuid
from time import monotonic

import structlog
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.clear_contextvars()
        return response


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int | None = None) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or get_settings().rate_limit_per_minute
        self.window_seconds = 60.0
        self._buckets: dict[str, tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.requests_per_minute <= 0 or request.url.path == "/metrics":
            return await call_next(request)
        key = client_rate_limit_key(request)
        now = monotonic()
        window_started, count = self._buckets.get(key, (now, 0))
        if now - window_started >= self.window_seconds:
            window_started, count = now, 0
        count += 1
        self._buckets[key] = (window_started, count)
        if count > self.requests_per_minute:
            return JSONResponse(
                {"code": "rate_limit_exceeded", "message": "Rate limit exceeded.", "details": {}},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(int(self.window_seconds - (now - window_started)))},
            )
        return await call_next(request)


def client_rate_limit_key(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"
