from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import redis.asyncio as aioredis

from shared.domain import AssetType

# ── cache key helpers (also imported by pipeline_api.services) ───────────────


def _truncate_to_second(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(microsecond=0)


def pit_cache_key(
    dataset_version: int,
    satellite_id: str,
    asset_type: AssetType,
    timestamp: datetime,
) -> str:
    ts = _truncate_to_second(timestamp).isoformat()
    return f"v{dataset_version}:{satellite_id}:{asset_type}:pit:{ts}"


def bulk_cache_key(
    composite_version: str,
    satellite_id: str,
    timestamp: datetime,
) -> str:
    ts = _truncate_to_second(timestamp).isoformat()
    return f"v{composite_version}:{satellite_id}:bulk:{ts}"


def composite_dataset_version(versions: dict[AssetType, int]) -> str:
    """Deterministic composite string used in bulk cache keys.

    Sorted so the key is identical regardless of dict insertion order.
    Any asset_type version change produces a different composite, invalidating
    the bulk cache entry.
    """
    return ",".join(f"{at}={v}" for at, v in sorted(versions.items()))


def _dataset_version_redis_key(satellite_id: str, asset_type: AssetType) -> str:
    return f"dataset_version:{satellite_id}:{asset_type}"


# ── interface ────────────────────────────────────────────────────────────────


class CacheRepository(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def get_dataset_version(
        self, satellite_id: str, asset_type: AssetType
    ) -> int: ...

    @abstractmethod
    async def incr_dataset_version(
        self, satellite_id: str, asset_type: AssetType
    ) -> int: ...


# ── Redis implementation ─────────────────────────────────────────────────────


class CacheRepositoryRedis(CacheRepository):
    def __init__(self, client: aioredis.Redis) -> None:  # type: ignore[type-arg]
        self._client = client

    async def get(self, key: str) -> str | None:
        val = await self._client.get(key)
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.setex(key, ttl_seconds, value)

    async def get_dataset_version(
        self, satellite_id: str, asset_type: AssetType
    ) -> int:
        val = await self._client.get(_dataset_version_redis_key(satellite_id, asset_type))
        return int(val) if val is not None else 0

    async def incr_dataset_version(
        self, satellite_id: str, asset_type: AssetType
    ) -> int:
        return int(
            await self._client.incr(_dataset_version_redis_key(satellite_id, asset_type))
        )
