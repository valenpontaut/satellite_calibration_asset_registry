from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field


class AssetType(StrEnum):
    DARKFRAME = "darkframe"
    GRAYFRAME = "grayframe"
    VICARIOUS_CAL_GAINS = "vicarious_cal_gains"
    BODY_TO_PAYLOAD = "body_to_payload"


class StorageFormat(StrEnum):
    NPY = "npy"
    JSON = "json"


class AuditOperation(StrEnum):
    CREATE = "CREATE"
    EXTEND = "EXTEND"
    SPLIT = "SPLIT"
    FULL_COVERAGE_DELETE = "FULL_COVERAGE_DELETE"
    RETIRE = "RETIRE"


class OverlapType(StrEnum):
    EXTEND = "EXTEND"
    SPLIT = "SPLIT"
    FULL_COVERAGE = "FULL_COVERAGE"


class AssetDefinition(BaseModel):
    asset_type: AssetType
    schema_version: str
    storage_format: StorageFormat
    description: str = ""


class AssetVersion(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    satellite_id: str
    asset_type: AssetType
    schema_version: str
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None
    blob_ref: str

    def is_valid_at(self, timestamp: datetime) -> bool:
        # Half-open interval: valid_from <= timestamp < valid_to; valid_to=None means open-ended.
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC required)")
        if timestamp < self.valid_from:
            return False
        if self.valid_to is None:
            return True
        return timestamp < self.valid_to


class AuditLogEntry(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    asset_version_id: uuid.UUID
    operation: AuditOperation
    operator_id: str
    occurred_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    details: dict[str, Any]
