from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.i18n.locale import normalize_locale, parse_accept_language


class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        explicit_locale = request.query_params.get("locale") or request.headers.get("X-Locale")
        if explicit_locale:
            request.state.locale = normalize_locale(explicit_locale)
        else:
            request.state.locale = parse_accept_language(request.headers.get("Accept-Language"))
        response = await call_next(request)
        response.headers["Content-Language"] = request.state.locale
        return response
