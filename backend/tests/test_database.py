from types import SimpleNamespace

import app.database as database


def test_init_db_invokes_metadata(monkeypatch):
    captured = {}

    def fake_create_all(engine):
        captured["engine"] = engine

    dummy_engine = object()
    monkeypatch.setattr(database, "metadata", SimpleNamespace(create_all=fake_create_all))
    monkeypatch.setattr(database, "engine", dummy_engine)

    database.init_db()

    assert captured["engine"] is dummy_engine
