from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime

from pipeline_api.services.asset_resolution_service import AssetResolutionService
from shared.domain import AssetType

router = APIRouter()


def _get_service(request: Request) -> AssetResolutionService:
    return request.app.state.service  # type: ignore[no-any-return]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
