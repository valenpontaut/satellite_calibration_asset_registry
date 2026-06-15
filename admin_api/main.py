from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from admin_api.routers.assets import router as assets_router
from admin_api.services.asset_admin_service import AssetAdminService
from shared.config import get_settings
from shared.repositories import (
    AdminMetadataRepositoryPostgres,
    CacheRepositoryRedis,
    ObjectStorageRepositoryS3,
)
from shared.validation.definitions import AssetDefinitionRegistry
from shared.validation.service import AssetValidationService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        settings.redis_url, decode_responses=False
    )
    app.state.service = AssetAdminService(
        validation_service=AssetValidationService(AssetDefinitionRegistry()),
        metadata_repo=AdminMetadataRepositoryPostgres(),
        storage_repo=ObjectStorageRepositoryS3(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        ),
        cache_repo=CacheRepositoryRedis(redis_client),
        engine=engine,
    )
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(title="SCAR Admin API", version="0.1.0", lifespan=lifespan)
app.include_router(assets_router)
