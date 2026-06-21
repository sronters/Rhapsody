from __future__ import annotations


def plural_category(locale: str, count: int) -> str:
    language = locale.lower().split("-", maxsplit=1)[0]
    if language == "ru":
        mod10 = count % 10
        mod100 = count % 100
        if mod10 == 1 and mod100 != 11:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        return "many"
    return "one" if count == 1 else "other"
