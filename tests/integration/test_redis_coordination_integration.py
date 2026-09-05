import asyncio

import fakeredis.aioredis

from sentinel.infrastructure.coordination import RedisCoordinator


def test_redis_coordinator_exercises_real_async_redis_commands():
    async def scenario():
        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        coordinator = RedisCoordinator(client, namespace="integration")
        try:
            assert await coordinator.cache_set("key", "value", ttl_seconds=30)
            assert await coordinator.cache_get("key") == "value"

            assert await coordinator.idempotency_hint_set("idem", "txn", ttl_seconds=30)
            assert not await coordinator.idempotency_hint_set("idem", "other", ttl_seconds=30)
            assert await coordinator.idempotency_hint_get("idem") == "txn"

            results = await asyncio.gather(
                *(
                    coordinator.idempotency_hint_set("race", "txn", ttl_seconds=30)
                    for _ in range(32)
                )
            )
            assert sum(results) == 1

            assert await coordinator.cache_set("stale", "value", ttl_seconds=1)
            await asyncio.sleep(1.1)
            assert await coordinator.cache_get("stale") is None

            async with coordinator.lock("resource", timeout_seconds=30):
                assert await coordinator.cache_get("key") == "value"

            async with coordinator.lock("expiring", timeout_seconds=1):
                await asyncio.sleep(1.1)
            async with coordinator.lock("expiring", timeout_seconds=1):
                pass

            first = await coordinator.rate_limit("requests", limit=2, window_seconds=30)
            second = await coordinator.rate_limit("requests", limit=2, window_seconds=30)
            third = await coordinator.rate_limit("requests", limit=2, window_seconds=30)
            assert first.allowed and second.allowed and not third.allowed
            assert third.count == 3
        finally:
            await coordinator.close()

    asyncio.run(scenario())