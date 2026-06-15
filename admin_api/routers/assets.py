from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import AwareDatetime, BaseModel

from admin_api.services.asset_admin_service import AssetAdminService
from shared.domain import AssetType
from shared.validation.validators import AssetValidationError

router = APIRouter()


def _get_service(request: Request) -> AssetAdminService:
    return request.app.state.service  # type: ignore[no-any-return]


class RetireRequest(BaseModel):
    retired_at: AwareDatetime
    operator_id: str


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/assets", status_code=201)
async def create_asset(
    satellite_id: Annotated[str, Form()],
    asset_type: Annotated[AssetType, Form()],
    valid_from: Annotated[AwareDatetime, Form()],
    operator_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    service: Annotated[AssetAdminService, Depends(_get_service)],
    valid_to: Annotated[AwareDatetime | None, Form()] = None,
) -> dict[str, Any]:
    content = await file.read()
    try:
        version = await service.create_asset_version(
            satellite_id=satellite_id,
            asset_type=asset_type,
            valid_from=valid_from,
            valid_to=valid_to,
            file_content=content,
            operator_id=operator_id,
        )
    except AssetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return version.model_dump(mode="json")


@router.delete("/assets/{version_id}/retire")
async def retire_asset(
    version_id: uuid.UUID,
    body: RetireRequest,
    service: Annotated[AssetAdminService, Depends(_get_service)],
) -> dict[str, Any]:
    try:
        version = await service.retire_asset_version(
            version_id=version_id,
            retired_at=body.retired_at,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return version.model_dump(mode="json")
