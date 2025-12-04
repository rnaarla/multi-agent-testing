"""Distributed locking helpers backed by Redis."""

from contextlib import contextmanager
from typing import Iterator
import os

import redis


class RedisLockError(RuntimeError):
    """Raised when a distributed lock cannot be acquired."""


def _redis_client() -> redis.Redis:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(redis_url, decode_responses=False)


@contextmanager
def redis_lock(key: str, ttl: int = 60, wait_timeout: int = 10) -> Iterator[None]:
    """Acquire a Redis-based lock for the duration of the context."""

    client = _redis_client()
    lock = client.lock(name=f"lock:{key}", timeout=ttl, blocking_timeout=wait_timeout)
    acquired = lock.acquire(blocking=True)
    if not acquired:
        raise RedisLockError(f"Could not acquire lock for key '{key}' within {wait_timeout}s")

    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            # Lock expired before release; nothing else to do
            pass
