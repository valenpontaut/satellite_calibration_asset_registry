from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import boto3
import redis.asyncio as aioredis
from botocore.config import Config as BotocoreConfig
from fastapi import FastAPI
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.ext.asyncio import create_async_engine

from pipeline_api.routers.assets import router as assets_router
from pipeline_api.services.asset_resolution_service import AssetResolutionService
from shared.config import get_settings
from shared.repositories import (
    CacheRepositoryRedis,
    ObjectStorageRepositoryS3,
    PipelineMetadataRepositoryPostgres,
)


class _ServiceJsonFormatter(JsonFormatter):
    def __init__(self, service: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service = service

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["service"] = self._service
        if "levelname" in log_record:
            log_record["level"] = log_record.pop("levelname")
        if "asctime" in log_record:
            log_record["timestamp"] = log_record.pop("asctime")


def _configure_logging(service_name: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        _ServiceJsonFormatter(
            service_name,
            fmt="%(asctime)s %(levelname)s %(message)s",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.addHandler(handler)
        uv.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging("pipeline-api")
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        settings.redis_url, decode_responses=False
    )
    s3_client: Any = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=BotocoreConfig(signature_version="s3v4"),
    )
    app.state.engine = engine
    app.state.redis_client = redis_client
    app.state.s3_client = s3_client
    app.state.s3_bucket = settings.s3_bucket
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
    await redis_client.close()


app = FastAPI(title="SCAR Pipeline API", version="0.1.0", lifespan=lifespan)
app.include_router(assets_router)
