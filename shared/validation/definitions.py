from __future__ import annotations

from shared.domain import AssetDefinition, AssetType, StorageFormat
from shared.validation.validators import (
    AssetValidator,
    BodyToPayloadJsonValidator,
    Npy2DFloatArrayValidator,
    VicariousCalGainsJsonValidator,
)


class UnknownAssetTypeError(Exception):
    pass


_DEFINITIONS: dict[AssetType, AssetDefinition] = {
    AssetType.DARKFRAME: AssetDefinition(
        asset_type=AssetType.DARKFRAME,
        schema_version="1.0",
        storage_format=StorageFormat.NPY,
    ),
    AssetType.GRAYFRAME: AssetDefinition(
        asset_type=AssetType.GRAYFRAME,
        schema_version="1.0",
        storage_format=StorageFormat.NPY,
    ),
    AssetType.VICARIOUS_CAL_GAINS: AssetDefinition(
        asset_type=AssetType.VICARIOUS_CAL_GAINS,
        schema_version="1.0",
        storage_format=StorageFormat.JSON,
    ),
    AssetType.BODY_TO_PAYLOAD: AssetDefinition(
        asset_type=AssetType.BODY_TO_PAYLOAD,
        schema_version="1.0",
        storage_format=StorageFormat.JSON,
    ),
}

_VALIDATORS: dict[AssetType, AssetValidator] = {
    AssetType.DARKFRAME: Npy2DFloatArrayValidator(),
    AssetType.GRAYFRAME: Npy2DFloatArrayValidator(),
    AssetType.VICARIOUS_CAL_GAINS: VicariousCalGainsJsonValidator(),
    AssetType.BODY_TO_PAYLOAD: BodyToPayloadJsonValidator(),
}


class AssetDefinitionRegistry:
    def get_definition(self, asset_type: AssetType) -> AssetDefinition:
        try:
            return _DEFINITIONS[asset_type]
        except KeyError:
            raise UnknownAssetTypeError(
                f"No definition registered for {asset_type!r}"
            ) from None

    def get_validator(self, asset_type: AssetType) -> AssetValidator:
        try:
            return _VALIDATORS[asset_type]
        except KeyError:
            raise UnknownAssetTypeError(
                f"No validator registered for {asset_type!r}"
            ) from None
