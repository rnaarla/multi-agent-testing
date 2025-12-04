import pytest

from app.utils import locks


def test_redis_lock_acquires_and_handles_release(monkeypatch):
    events = {"release_attempts": 0}

    class DummyLock:
        def __init__(self):
            self.acquired = False

        def acquire(self, blocking=True):
            self.acquired = True
            return True

        def release(self):
            events["release_attempts"] += 1
            raise locks.redis.exceptions.LockError()

    class DummyClient:
        def lock(self, name, timeout, blocking_timeout):
            events["lock_name"] = name
            events["timeout"] = timeout
            events["blocking_timeout"] = blocking_timeout
            return DummyLock()

    monkeypatch.setattr(locks, "_redis_client", lambda: DummyClient())

    with locks.redis_lock("test", ttl=5, wait_timeout=1):
        assert events["lock_name"] == "lock:test"
        assert events["timeout"] == 5
        assert events["blocking_timeout"] == 1

    assert events["release_attempts"] == 1


def test_redis_lock_failure(monkeypatch):
    class DummyLock:
        def acquire(self, blocking=True):
            return False

    class DummyClient:
        def lock(self, name, timeout, blocking_timeout):
            return DummyLock()

    monkeypatch.setattr(locks, "_redis_client", lambda: DummyClient())

    with pytest.raises(locks.RedisLockError):
        with locks.redis_lock("test"):
            pass


def test_redis_client_uses_env(monkeypatch):
    calls = {}

    class DummyRedis:
        @staticmethod
        def from_url(url, decode_responses):
            calls["url"] = url
            calls["decode"] = decode_responses
            return "client"

    monkeypatch.setenv("REDIS_URL", "redis://example/5")
    monkeypatch.setattr(locks.redis, "Redis", DummyRedis)

    client = locks._redis_client()
    assert client == "client"
    assert calls["url"] == "redis://example/5"
    assert calls["decode"] is False
