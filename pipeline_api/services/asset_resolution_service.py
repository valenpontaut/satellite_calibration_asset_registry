from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from shared.config import Settings
from shared.domain import AssetType, AssetVersion
from shared.repositories import (
    CacheRepository,
    ObjectStorageRepository,
    PipelineMetadataRepository,
    bulk_cache_key,
    composite_dataset_version,
    pit_cache_key,
)


def _fmt_timestamp(ts: datetime) -> str:
    return ts.astimezone(UTC).replace(microsecond=0).isoformat()


class AssetResolutionService:
    def __init__(
        self,
        pipeline_metadata: PipelineMetadataRepository,
        cache: CacheRepository,
        storage: ObjectStorageRepository,
        settings: Settings,
    ) -> None:
        self._pipeline_metadata = pipeline_metadata
        self._cache = cache
        self._storage = storage
        self._settings = settings

    async def resolve_point_in_time(
        self,
        satellite_id: str,
        asset_type: AssetType,
        timestamp: datetime,
    ) -> dict[str, Any]:
        dataset_version = await self._cache.get_dataset_version(satellite_id, asset_type)
        key = self._build_cache_key(satellite_id, asset_type, dataset_version, timestamp)

        hit = await self._cache.get(key)
        if hit is not None:
            return json.loads(hit)  # type: ignore[no-any-return]

        version = await self._pipeline_metadata.find_point_in_time(
            satellite_id, asset_type, timestamp
        )
        ttl = self._ttl_for(version)

        if version is None:
            result: dict[str, Any] = {
                "found": False,
                "satellite_id": satellite_id,
                "asset_type": str(asset_type),
                "timestamp": _fmt_timestamp(timestamp),
            }
        else:
            result = {
                "found": True,
                "asset_version": version.model_dump(mode="json"),
                "presigned_url": self._storage.generate_presigned_url(
                    version.blob_ref, self._settings.presigned_url_expires_in
                ),
            }

        await self._cache.set(key, json.dumps(result, default=str), ttl)
        return result

    async def resolve_bulk(
        self,
        satellite_id: str,
        timestamp: datetime,
    ) -> dict[str, dict[str, Any]]:
        versions_by_type = {
            at: await self._cache.get_dataset_version(satellite_id, at)
            for at in AssetType
        }
        composite = composite_dataset_version(versions_by_type)
        key = self._build_cache_key(satellite_id, None, composite, timestamp, bulk=True)

        hit = await self._cache.get(key)
        if hit is not None:
            return json.loads(hit)  # type: ignore[no-any-return]

        bulk = await self._pipeline_metadata.find_bulk(satellite_id, timestamp)

        result: dict[str, dict[str, Any]] = {}
        for at, version in bulk.items():
            if version is None:
                result[str(at)] = {
                    "found": False,
                    "satellite_id": satellite_id,
                    "asset_type": str(at),
                    "timestamp": _fmt_timestamp(timestamp),
                }
            else:
                result[str(at)] = {
                    "found": True,
                    "asset_version": version.model_dump(mode="json"),
                    "presigned_url": self._storage.generate_presigned_url(
                        version.blob_ref, self._settings.presigned_url_expires_in
                    ),
                }

        # Use the most conservative TTL: if any found version is open-ended,
        # the whole bulk result could change soon.
        ttl = min(
            (self._ttl_for(v) for v in bulk.values() if v is not None),
            default=self._settings.cache_short_ttl_seconds,
        )
        await self._cache.set(key, json.dumps(result, default=str), ttl)
        return result

    def _build_cache_key(
        self,
        satellite_id: str,
        asset_type: AssetType | None,
        dataset_version: int | str,
        timestamp: datetime,
        bulk: bool = False,
    ) -> str:
        if bulk:
            return bulk_cache_key(str(dataset_version), satellite_id, timestamp)
        return pit_cache_key(int(dataset_version), satellite_id, asset_type, timestamp)  # type: ignore[arg-type]

    def _ttl_for(self, version: AssetVersion | None) -> int:
        if version is None or version.valid_to is None:
            return self._settings.cache_short_ttl_seconds
        return self._settings.cache_long_ttl_seconds
