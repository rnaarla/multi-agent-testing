#!/usr/bin/env python
"""
Generate the OpenAPI schema for the Multi-Agent Testing API.

Usage:
    python backend/scripts/generate_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from app.main import app  # type: ignore


def main() -> None:
    schema = app.openapi()
    output_path = Path(__file__).resolve().parents[1] / "docs" / "openapi-schema.json"
    output_path.write_text(json.dumps(schema, indent=2))
    print(f"Wrote OpenAPI schema to {output_path}")


if __name__ == "__main__":
    main()

