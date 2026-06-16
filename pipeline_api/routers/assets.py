from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime

from pipeline_api.services.asset_resolution_service import AssetResolutionService
from shared.domain import AssetType
from shared.health import check_dependencies

router = APIRouter()


def _get_service(request: Request) -> AssetResolutionService:
    return request.app.state.service  # type: ignore[no-any-return]


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    deps = await check_dependencies(
        engine=request.app.state.engine,
        redis_client=request.app.state.redis_client,
        s3_client=request.app.state.s3_client,
        s3_bucket=request.app.state.s3_bucket,
    )
    status = "ok" if all(v == "ok" for v in deps.values()) else "degraded"
    return JSONResponse(
        {"status": status, "dependencies": deps},
        status_code=200 if status == "ok" else 503,
    )


@router.get("/resolve")
async def resolve_point_in_time(
    satellite_id: str,
    asset_type: AssetType,
    timestamp: AwareDatetime,
    service: Annotated[AssetResolutionService, Depends(_get_service)],
) -> dict[str, Any]:
    return await service.resolve_point_in_time(satellite_id, asset_type, timestamp)


@router.get("/resolve/bulk")
async def resolve_bulk(
    satellite_id: str,
    timestamp: AwareDatetime,
    service: Annotated[AssetResolutionService, Depends(_get_service)],
) -> dict[str, Any]:
    return await service.resolve_bulk(satellite_id, timestamp)
