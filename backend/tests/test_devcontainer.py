from __future__ import annotations

import json
from pathlib import Path


def test_devcontainer_configuration():
    root = Path(__file__).resolve().parents[2]
    devcontainer_path = root / ".devcontainer" / "devcontainer.json"
    dockerfile_path = root / ".devcontainer" / "Dockerfile"

    assert devcontainer_path.exists(), "devcontainer.json missing"
    data = json.loads(devcontainer_path.read_text())

    assert data["name"] == "multi-agent-testing-dev"
    assert data["build"]["dockerfile"] == "Dockerfile"
    assert data["build"]["context"] == ".."
    assert "ms-python.python" in data["customizations"]["vscode"]["extensions"]

    dockerfile = dockerfile_path.read_text()
    assert "python:3.11-slim" in dockerfile
    assert "pip install -r /tmp/requirements.txt" in dockerfile

