from pathlib import Path

import pytest

from app.services import artifact_storage as artifact_module


def test_artifact_storage_local_save(tmp_path):
    storage = artifact_module.ArtifactStorage(backend="local", base_dir=tmp_path)
    payload = {"foo": "bar"}
    saved_path = storage.save_json(run_id=7, name="trace", payload=payload)

    path = Path(saved_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == '{"foo": "bar"}'


def test_artifact_storage_s3_success(monkeypatch):
    uploads = []

    class DummyClient:
        def put_object(self, **kwargs):
            uploads.append(kwargs)

    class DummyBoto:
        def client(self, name):  # pragma: no cover - simple passthrough
            assert name == "s3"
            return DummyClient()

    monkeypatch.setattr(artifact_module, "boto3", DummyBoto())

    storage = artifact_module.ArtifactStorage(backend="s3", bucket="demo", prefix="prefix")
    uri = storage.save_json(1, "trace", {"value": 1})

    assert uri == "s3://demo/prefix/run_1_trace.json"
    assert uploads[0]["Bucket"] == "demo"
    assert uploads[0]["ContentType"] == "application/json"


def test_artifact_storage_s3_failure(monkeypatch):
    class DummyError(Exception):
        pass

    class FailingClient:
        def put_object(self, **kwargs):
            raise DummyError("boom")

    monkeypatch.setattr(artifact_module, "boto3", type("Boto", (), {"client": lambda self, name: FailingClient()})())
    monkeypatch.setattr(artifact_module, "BotoCoreError", DummyError)
    monkeypatch.setattr(artifact_module, "ClientError", DummyError)

    storage = artifact_module.ArtifactStorage(backend="s3", bucket="demo")

    with pytest.raises(RuntimeError):
        storage.save_json(2, "trace", {"value": 2})
