"""Write the API's OpenAPI schema to backend/openapi.json (committed; a unit test checks it).

uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def render() -> str:
    schema: dict[str, Any] = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OPENAPI_PATH.write_text(render())
    print(f"wrote {OPENAPI_PATH}")
