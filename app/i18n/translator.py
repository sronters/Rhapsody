from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from app.i18n.locale import default_locale, normalize_locale


class MissingTranslationError(KeyError):
    pass


@lru_cache
def load_catalog(locale: str) -> dict[str, Any]:
    normalized = normalize_locale(locale)
    catalog_path = files("app.i18n.catalogs").joinpath(f"{normalized}.json")
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def translate(key: str, locale: str | None = None, **params: object) -> str:
    normalized = normalize_locale(locale or default_locale())
    value = _lookup(load_catalog(normalized), key)
    if value is None and normalized != default_locale():
        value = _lookup(load_catalog(default_locale()), key)
    if value is None:
        raise MissingTranslationError(key)
    if not isinstance(value, str):
        raise MissingTranslationError(key)
    return value.format(**params)


def t(key: str, locale: str | None = None, **params: object) -> str:
    return translate(key, locale, **params)


def _lookup(catalog: dict[str, Any], key: str) -> object | None:
    current: object = catalog
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
