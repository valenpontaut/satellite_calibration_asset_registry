from __future__ import annotations

from pydantic import BaseModel

from shared.domain import AssetType, StorageFormat
from shared.validation.definitions import AssetDefinitionRegistry


class ValidatedAsset(BaseModel):
    asset_type: AssetType
    schema_version: str
    storage_format: StorageFormat


class AssetValidationService:
    def __init__(self, registry: AssetDefinitionRegistry) -> None:
        self._registry = registry

    def validate(self, asset_type: AssetType, data: bytes) -> ValidatedAsset:
        definition = self._registry.get_definition(asset_type)
        validator = self._registry.get_validator(asset_type)
        validator.validate(data)  # raises AssetValidationError on bad content
        return ValidatedAsset(
            asset_type=definition.asset_type,
            schema_version=definition.schema_version,
            storage_format=definition.storage_format,
        )
