from importlib import import_module


def test_fastapi_app_exposes_instance():
    """Basic smoke test to ensure the FastAPI app is importable."""
    module = import_module("app.main")
    assert hasattr(module, "app"), "FastAPI application instance missing"
