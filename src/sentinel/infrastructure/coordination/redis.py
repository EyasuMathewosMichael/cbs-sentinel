"""Redis-backed ephemeral coordination primitives for SENTINEL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError


class RedisCoordinationError(RuntimeError):
    """Base error for non-authoritative Redis coordination failures."""


@dataclass(frozen=True, slots=True)
class RedisRateLimitResult:
    """A rate-limit decision; it is never a financial decision."""

    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int


_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


class RedisCoordinator:
    """Provide cache, fast idempotency, locks, and rate limiting only."""

    def __init__(self, client: Any, *, namespace: str = "sentinel") -> None:
        if not namespace or namespace.strip() != namespace:
            raise ValueError("namespace must not be empty or contain outer whitespace")
        self._client = client
        self._namespace = namespace

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._client.aclose()

    async def cache_get(self, key: str) -> str | None:
        """Read an ephemeral cached value; callers must tolerate a cache miss."""
        try:
            return cast(str | None, await self._client.get(self._key("cache", key)))
        except (RedisError, TimeoutError):
            return None

    async def cache_set(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """Cache a value with mandatory expiry to prevent unbounded ephemeral state."""
        _validate_key(key)
        _validate_ttl(ttl_seconds)
        try:
            return bool(await self._client.set(self._key("cache", key), value, ex=ttl_seconds))
        except (RedisError, TimeoutError):
            return False

    async def cache_delete(self, key: str) -> int:
        """Delete an ephemeral cached value."""
        _validate_key(key)
        try:
            return int(await self._client.delete(self._key("cache", key)))
        except (RedisError, TimeoutError):
            return 0

    async def idempotency_hint_get(self, idempotency_key: str) -> str | None:
        """Return a fast-path hint; PostgreSQL remains the durable authority."""
        try:
            return cast(
                str | None,
                await self._client.get(self._key("idempotency", idempotency_key)),
            )
        except (RedisError, TimeoutError):
            return None

    async def idempotency_hint_set(
        self, idempotency_key: str, transaction_id: str, *, ttl_seconds: int
    ) -> bool:
        """Store a best-effort idempotency hint with set-if-absent semantics."""
        _validate_key(idempotency_key)
        _validate_key(transaction_id)
        _validate_ttl(ttl_seconds)
        try:
            return bool(
                await self._client.set(
                    self._key("idempotency", idempotency_key),
                    transaction_id,
                    ex=ttl_seconds,
                    nx=True,
                )
            )
        except (RedisError, TimeoutError):
            return False

    @asynccontextmanager
    async def lock(
        self,
        name: str,
        *,
        timeout_seconds: int,
        blocking_timeout_seconds: float | None = None,
    ) -> AsyncIterator[None]:
        """Hold a bounded distributed lock for coordination, never for ledger truth."""
        _validate_key(name)
        _validate_ttl(timeout_seconds)
        if blocking_timeout_seconds is not None and blocking_timeout_seconds < 0:
            raise ValueError("blocking_timeout_seconds must not be negative")
        lock = self._client.lock(
            self._key("lock", name),
            timeout=timeout_seconds,
            blocking_timeout=blocking_timeout_seconds,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise RedisCoordinationError(f"could not acquire Redis lock: {name}")
        try:
            yield
        finally:
            try:
                await cast(Any, lock.release)()
            except (LockError, RedisError, TimeoutError):
                pass

    async def rate_limit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RedisRateLimitResult:
        """Apply an atomic fixed-window limit for operational traffic."""
        _validate_key(key)
        if limit < 1:
            raise ValueError("limit must be positive")
        _validate_ttl(window_seconds)
        try:
            count, ttl = await self._client.eval(
                _RATE_LIMIT_SCRIPT,
                1,
                self._key("rate", key),
                str(window_seconds),
            )
        except (RedisError, TimeoutError):
            return RedisRateLimitResult(True, 0, limit, 0)
        count = int(count)
        ttl = max(int(ttl), 0)
        return RedisRateLimitResult(count <= limit, count, limit, ttl)

    def _key(self, category: str, key: str) -> str:
        _validate_key(key)
        return f"{self._namespace}:{category}:{key}"


def create_redis_client(redis_url: str, *, max_connections: int = 20) -> Redis:
    """Create a response-decoding Redis client with bounded connections."""
    if not redis_url.startswith(("redis://", "rediss://")):
        raise ValueError("redis_url must use redis:// or rediss://")
    if max_connections < 1:
        raise ValueError("max_connections must be positive")
    return cast(
        Redis,
        Redis.from_url(
            redis_url,
            decode_responses=True,
            max_connections=max_connections,
            health_check_interval=30,
            socket_connect_timeout=2,
            socket_timeout=2,
        ),
    )


def _validate_key(value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("Redis keys must be non-empty strings without outer whitespace")


def _validate_ttl(value: int) -> None:
    if value < 1:
        raise ValueError("ttl_seconds must be positive")