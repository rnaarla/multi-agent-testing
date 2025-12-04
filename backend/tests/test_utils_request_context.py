from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.utils.request_context import RequestContextMiddleware, get_correlation_id


def test_request_context_middleware_sets_headers():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/context")
    async def get_context(request: Request):
        return {"id": get_correlation_id(request)}

    client = TestClient(app)
    response = client.get("/context", headers={"X-Request-ID": "abc"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "abc"
    assert "X-Response-Time-ms" in response.headers
    assert response.json()["id"] == "abc"


def test_get_correlation_id_handles_missing_request():
    assert get_correlation_id(None) is None
