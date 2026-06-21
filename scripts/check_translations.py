from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "app" / "i18n" / "catalogs"
DOCS_CONFIG = ROOT / "docs-site" / "docs.json"
PLACEHOLDER_PATTERN = re.compile(r"{([^{}]+)}")


def main() -> int:
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CATALOG_DIR.glob("*.json"))
    }
    failures: list[str] = []
    if not {"en", "ru"}.issubset(catalogs):
        failures.append("Missing required en/ru catalogs.")
    flattened = {locale: flatten(payload) for locale, payload in catalogs.items()}
    reference_keys = set(flattened.get("en", {}))
    for locale, values in flattened.items():
        keys = set(values)
        missing = sorted(reference_keys - keys)
        extra = sorted(keys - reference_keys)
        if missing:
            failures.append(f"{locale}: missing keys: {', '.join(missing)}")
        if extra:
            failures.append(f"{locale}: extra keys: {', '.join(extra)}")
        for key, value in values.items():
            if not value.strip():
                failures.append(f"{locale}.{key}: empty translation")
            if "TODO" in value:
                failures.append(f"{locale}.{key}: contains TODO")
            en_value = flattened.get("en", {}).get(key)
            if en_value is not None and placeholders(value) != placeholders(en_value):
                failures.append(f"{locale}.{key}: placeholder mismatch")
    failures.extend(check_docs_languages())
    if failures:
        print("\n".join(failures))
        return 1
    print("Translation catalogs and docs language structure are consistent.")
    return 0


def flatten(payload: dict, prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in payload.items():
        child_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, child_key))
        elif isinstance(value, str):
            result[child_key] = value
        else:
            raise TypeError(f"{child_key}: expected string or object")
    return result


def placeholders(value: str) -> set[str]:
    return set(PLACEHOLDER_PATTERN.findall(value))


def check_docs_languages() -> list[str]:
    if not DOCS_CONFIG.exists():
        return []
    docs = json.loads(DOCS_CONFIG.read_text(encoding="utf-8"))
    languages = docs.get("navigation", {}).get("languages", [])
    by_language = {item.get("language"): item for item in languages}
    failures: list[str] = []
    if set(by_language) != {"en", "ru"}:
        failures.append("docs-site/docs.json must expose exactly en and ru languages.")
        return failures
    en_pages = page_suffixes(by_language["en"], "en/")
    ru_pages = page_suffixes(by_language["ru"], "ru/")
    if en_pages != ru_pages:
        failures.append("docs en/ru page structures differ.")
    for item in by_language.values():
        for group in item.get("groups", []):
            for page in group.get("pages", []):
                path = ROOT / "docs-site" / f"{page}.mdx"
                if not path.exists():
                    failures.append(f"Missing docs page: {page}.mdx")
    return failures


def page_suffixes(language: dict, prefix: str) -> list[str]:
    pages: list[str] = []
    for group in language.get("groups", []):
        for page in group.get("pages", []):
            pages.append(page.removeprefix(prefix))
    return pages


if __name__ == "__main__":
    raise SystemExit(main())
