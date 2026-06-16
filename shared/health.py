from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_TIMEOUT = 2.0


async def _check_db(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis(redis_client: aioredis.Redis) -> None:  # type: ignore[type-arg]
    await redis_client.ping()


async def _check_s3(s3_client: Any, bucket: str) -> None:
    await asyncio.to_thread(s3_client.head_bucket, Bucket=bucket)


async def _guarded(coro: Coroutine[Any, Any, None]) -> str:
    try:
        await asyncio.wait_for(coro, timeout=_TIMEOUT)
        return "ok"
    except Exception:
        return "error"


async def check_dependencies(
    engine: AsyncEngine,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
    s3_client: Any | None = None,
    s3_bucket: str | None = None,
) -> dict[str, str]:
    coros: list[Coroutine[Any, Any, str]] = [
        _guarded(_check_db(engine)),
        _guarded(_check_redis(redis_client)),
    ]
    keys = ["metadata_store", "cache"]

    if s3_client is not None and s3_bucket is not None:
        coros.append(_guarded(_check_s3(s3_client, s3_bucket)))
        keys.append("object_storage")

    results: tuple[str, ...] = await asyncio.gather(*coros)
    return dict(zip(keys, results))
