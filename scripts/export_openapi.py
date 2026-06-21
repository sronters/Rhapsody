from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    output_path = Path(__file__).resolve().parents[1] / "docs-site" / "openapi.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI schema written to {output_path}")


if __name__ == "__main__":
    main()
