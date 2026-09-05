import asyncio

import pytest
from redis.exceptions import RedisError

from sentinel.infrastructure.coordination import (
    RedisCoordinationError,
    RedisCoordinator,
    create_redis_client,
)


class FakeLock:
    def __init__(self, *, acquired=True):
        self.acquired = acquired
        self.released = False

    async def acquire(self):
        return self.acquired

    async def release(self):
        self.released = True


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.set_calls = []
        self.lock_instance = FakeLock()

    async def aclose(self):
        return None

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.set_calls.append((key, value, kwargs))
        if kwargs.get("nx") and key in self.values:
            return None
        self.values[key] = value
        return True

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def lock(self, *args, **kwargs):
        return self.lock_instance

    async def eval(self, script, numkeys, key, window_seconds):
        count = int(self.values.get(key, 0)) + 1
        self.values[key] = count
        return count, window_seconds


class FailedRedis(FakeRedis):
    async def get(self, key):
        raise RedisError("redis unavailable")

    async def set(self, key, value, **kwargs):
        raise RedisError("redis unavailable")

    async def delete(self, key):
        raise RedisError("redis unavailable")

    async def eval(self, script, numkeys, key, window_seconds):
        raise RedisError("redis unavailable")


def test_cache_and_idempotency_hints_are_namespaced_and_ttl_bound():
    client = FakeRedis()
    coordinator = RedisCoordinator(client, namespace="test")

    async def exercise():
        assert await coordinator.cache_set("item", "value", ttl_seconds=30)
        assert await coordinator.cache_get("item") == "value"
        assert await coordinator.idempotency_hint_set("idem", "txn", ttl_seconds=60)
        assert not await coordinator.idempotency_hint_set("idem", "txn-2", ttl_seconds=60)
        assert await coordinator.idempotency_hint_get("idem") == "txn"

    asyncio.run(exercise())

    assert client.set_calls == [
        ("test:cache:item", "value", {"ex": 30}),
        ("test:idempotency:idem", "txn", {"ex": 60, "nx": True}),
        ("test:idempotency:idem", "txn-2", {"ex": 60, "nx": True}),
    ]


def test_lock_releases_after_success_and_reports_acquisition_failure():
    client = FakeRedis()
    coordinator = RedisCoordinator(client)

    async def exercise():
        async with coordinator.lock("transaction", timeout_seconds=10):
            pass
        assert client.lock_instance.released
        client.lock_instance = FakeLock(acquired=False)
        with pytest.raises(RedisCoordinationError):
            async with coordinator.lock("transaction", timeout_seconds=10):
                pass

    asyncio.run(exercise())


def test_rate_limit_is_atomic_and_reports_retry_window():
    client = FakeRedis()
    coordinator = RedisCoordinator(client)

    async def exercise():
        first = await coordinator.rate_limit("api", limit=2, window_seconds=60)
        second = await coordinator.rate_limit("api", limit=2, window_seconds=60)
        third = await coordinator.rate_limit("api", limit=2, window_seconds=60)
        return first, second, third

    first, second, third = asyncio.run(exercise())
    assert first.allowed and second.allowed and not third.allowed
    assert (first.count, second.count, third.count) == (1, 2, 3)
    assert third.retry_after_seconds == 60


def test_invalid_redis_configuration_and_keys_are_rejected():
    with pytest.raises(ValueError):
        create_redis_client("http://localhost")
    with pytest.raises(ValueError):
        create_redis_client("redis://localhost", max_connections=0)

    coordinator = RedisCoordinator(FakeRedis())

    async def exercise():
        with pytest.raises(ValueError):
            await coordinator.cache_set(" ", "value", ttl_seconds=1)
        with pytest.raises(ValueError):
            await coordinator.cache_set("key", "value", ttl_seconds=0)
        with pytest.raises(ValueError):
            await coordinator.rate_limit("key", limit=0, window_seconds=1)

    asyncio.run(exercise())


def test_advisory_operations_fail_open_when_redis_is_unavailable():
    coordinator = RedisCoordinator(FailedRedis())

    async def exercise():
        assert await coordinator.cache_get("key") is None
        assert not await coordinator.cache_set("key", "value", ttl_seconds=1)
        assert await coordinator.cache_delete("key") == 0
        assert await coordinator.idempotency_hint_get("idem") is None
        assert not await coordinator.idempotency_hint_set("idem", "txn", ttl_seconds=1)
        result = await coordinator.rate_limit("api", limit=1, window_seconds=1)
        assert result.allowed
        assert result.count == 0

    asyncio.run(exercise())