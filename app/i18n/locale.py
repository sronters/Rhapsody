from __future__ import annotations

from collections.abc import Iterable

from app.core.config import get_settings


def configured_locales() -> list[str]:
    settings = get_settings()
    return [locale.lower() for locale in settings.supported_locales]


def default_locale() -> str:
    settings = get_settings()
    return normalize_locale(settings.default_locale, settings.supported_locales)


def normalize_locale(locale: str | None, supported: Iterable[str] | None = None) -> str:
    supported_locales = [item.lower() for item in (supported or configured_locales())]
    fallback = supported_locales[0] if supported_locales else "en"
    if not locale:
        return fallback
    normalized = locale.strip().lower().replace("_", "-")
    if normalized in supported_locales:
        return normalized
    language = normalized.split("-", maxsplit=1)[0]
    return language if language in supported_locales else fallback


def parse_accept_language(header: str | None, supported: Iterable[str] | None = None) -> str:
    supported_locales = [item.lower() for item in (supported or configured_locales())]
    if not header:
        return normalize_locale(None, supported_locales)
    candidates: list[tuple[float, str]] = []
    for raw_part in header.split(","):
        part = raw_part.strip()
        if not part:
            continue
        locale, _, params = part.partition(";")
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        candidates.append((quality, locale))
    if not candidates:
        return normalize_locale(None, supported_locales)
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, locale in candidates:
        normalized = locale.strip().lower().replace("_", "-")
        if normalized in supported_locales:
            return normalized
        language = normalized.split("-", maxsplit=1)[0]
        if language in supported_locales:
            return language
    return normalize_locale(None, supported_locales)
