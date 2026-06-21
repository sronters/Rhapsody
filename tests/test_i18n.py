from __future__ import annotations

import json
from pathlib import Path

from app.i18n.locale import normalize_locale, parse_accept_language
from app.i18n.pluralization import plural_category
from app.i18n.translator import t

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_key_parity() -> None:
    en = json.loads((ROOT / "app/i18n/catalogs/en.json").read_text(encoding="utf-8"))
    ru = json.loads((ROOT / "app/i18n/catalogs/ru.json").read_text(encoding="utf-8"))

    assert set(flatten(en)) == set(flatten(ru))


def test_unknown_locale_falls_back_to_default() -> None:
    assert normalize_locale("de-DE", ["en", "ru"]) == "en"
    assert t("telegram.language_saved", "de-DE") == "Language saved: English."


def test_accept_language_prefers_supported_language() -> None:
    assert parse_accept_language("kk-KZ,ru;q=0.9,en;q=0.5", ["en", "ru"]) == "ru"


def test_parameterized_translation() -> None:
    assert "Alpha" in t("telegram.setup_success", "en", workspace_name="Alpha", role="owner")
    assert "Alpha" in t("telegram.setup_success", "ru", workspace_name="Alpha", role="owner")


def test_pluralization_english_and_russian() -> None:
    assert plural_category("en", 1) == "one"
    assert plural_category("en", 2) == "other"
    assert plural_category("ru", 1) == "one"
    assert plural_category("ru", 2) == "few"
    assert plural_category("ru", 5) == "many"


def test_live_call_status_display_translation() -> None:
    assert t("live_calls.status.RECORDING", "en") == "Recording"
    assert t("live_calls.status.RECORDING", "ru") == "Идёт запись"


def flatten(payload: dict, prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in payload.items():
        child_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, child_key))
        else:
            result[child_key] = value
    return result
