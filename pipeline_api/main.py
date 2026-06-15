from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from pipeline_api.routers.assets import router as assets_router
from pipeline_api.services.asset_resolution_service import AssetResolutionService
from shared.config import get_settings
from shared.repositories import (
    CacheRepositoryRedis,
    ObjectStorageRepositoryS3,
    PipelineMetadataRepositoryPostgres,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        settings.redis_url, decode_responses=False
    )
    app.state.service = AssetResolutionService(
        pipeline_metadata=PipelineMetadataRepositoryPostgres(engine),
        cache=CacheRepositoryRedis(redis_client),
        storage=ObjectStorageRepositoryS3(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        ),
        settings=settings,
    )
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(title="SCAR Pipeline API", version="0.1.0", lifespan=lifespan)
app.include_router(assets_router)
