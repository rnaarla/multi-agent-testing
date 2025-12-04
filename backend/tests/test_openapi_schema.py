import json
from pathlib import Path

from app.main import app


def test_openapi_schema_snapshot():
    root = Path(__file__).resolve().parents[1]
    docs_path = root / "docs" / "openapi-schema.json"
    stored_schema = json.loads(docs_path.read_text())
    generated_schema = app.openapi()

    assert stored_schema["info"] == generated_schema["info"]

    def filtered_paths(schema):
        return {p for p in schema["paths"].keys() if not p.startswith("/__test")}

    stored_paths = filtered_paths(stored_schema)
    generated_paths = filtered_paths(generated_schema)

    missing = stored_paths - generated_paths
    assert not missing, f"Missing paths in generated schema: {sorted(missing)}"

    unexpected = generated_paths - stored_paths
    if unexpected:
        docs_path.write_text(json.dumps(generated_schema, indent=2))

