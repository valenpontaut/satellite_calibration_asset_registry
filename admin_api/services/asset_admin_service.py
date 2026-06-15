from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from shared.domain import (
    AssetType,
    AssetVersion,
    AuditLogEntry,
    AuditOperation,
    OverlapType,
)
from shared.repositories import (
    AdminMetadataRepository,
    CacheRepository,
    ObjectStorageRepository,
    generate_blob_ref,
)
from shared.repositories._tables import asset_versions as _asset_versions_table
from shared.validation.service import AssetValidationService


def _version_snapshot(version: AssetVersion) -> dict[str, Any]:
    return {
        "satellite_id": version.satellite_id,
        "asset_type": str(version.asset_type),
        "valid_from": version.valid_from.isoformat(),
        "valid_to": version.valid_to.isoformat() if version.valid_to else None,
        "blob_ref": version.blob_ref,
        "schema_version": version.schema_version,
    }


class AssetAdminService:
    def __init__(
        self,
        validation_service: AssetValidationService,
        metadata_repo: AdminMetadataRepository,
        storage_repo: ObjectStorageRepository,
        cache_repo: CacheRepository,
        engine: AsyncEngine,
    ) -> None:
        self._validation = validation_service
        self._metadata = metadata_repo
        self._storage = storage_repo
        self._cache = cache_repo
        self._engine = engine

    async def create_asset_version(
        self,
        satellite_id: str,
        asset_type: AssetType,
        valid_from: datetime,
        valid_to: datetime | None,
        file_content: bytes,
        operator_id: str,
    ) -> AssetVersion:
        # Validate content before any persistence
        validated = self._validation.validate(asset_type, file_content)

        # Persist blob before the metadata transaction so the row always
        # references an object that already exists in storage.
        blob_ref = generate_blob_ref(asset_type)
        self._storage.put_object(blob_ref, file_content)

        new_version = AssetVersion(
            satellite_id=satellite_id,
            asset_type=asset_type,
            schema_version=validated.schema_version,
            valid_from=valid_from,
            valid_to=valid_to,
            blob_ref=blob_ref,
        )

        async with self._engine.begin() as conn:
            overlap_entries = await self._resolve_overlaps(
                conn, satellite_id, asset_type, valid_from, valid_to, operator_id
            )
            await self._metadata.insert_version(conn, new_version)
            for entry in overlap_entries:
                await self._metadata.insert_audit_log(conn, entry)
            create_entry = AuditLogEntry(
                asset_version_id=new_version.id,
                operation=AuditOperation.CREATE,
                operator_id=operator_id,
                details=_version_snapshot(new_version),
            )
            await self._metadata.insert_audit_log(conn, create_entry)

        # Bump dataset_version once per write, after the transaction commits.
        await self._cache.incr_dataset_version(satellite_id, asset_type)
        return new_version

    async def retire_asset_version(
        self,
        version_id: uuid.UUID,
        retired_at: datetime,
        operator_id: str,
    ) -> AssetVersion:
        async with self._engine.begin() as conn:
            # Fetch the current row so we can snapshot its state before mutation.
            # AdminMetadataRepository has no find_by_id, so we query directly.
            row = (
                await conn.execute(
                    sa.select(_asset_versions_table).where(
                        _asset_versions_table.c.id == version_id
                    )
                )
            ).fetchone()
            if row is None:
                raise ValueError(f"AssetVersion {version_id} not found")

            existing = AssetVersion(
                id=row.id,
                satellite_id=row.satellite_id,
                asset_type=AssetType(row.asset_type),
                schema_version=row.schema_version,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                blob_ref=row.blob_ref,
            )
            snapshot = _version_snapshot(existing)

            updated = await self._metadata.update_version(
                conn, version_id, valid_to=retired_at
            )
            await self._metadata.insert_audit_log(
                conn,
                AuditLogEntry(
                    asset_version_id=version_id,
                    operation=AuditOperation.RETIRE,
                    operator_id=operator_id,
                    details=snapshot,
                ),
            )

        await self._cache.incr_dataset_version(
            existing.satellite_id, existing.asset_type
        )
        return updated

    async def _resolve_overlaps(
        self,
        conn: AsyncConnection,
        satellite_id: str,
        asset_type: AssetType,
        valid_from: datetime,
        valid_to: datetime | None,
        operator_id: str,
    ) -> list[AuditLogEntry]:
        overlapping = await self._metadata.find_overlapping(
            conn, satellite_id, asset_type, valid_from, valid_to
        )
        audit_entries: list[AuditLogEntry] = []

        for existing in overlapping:
            overlap_type = self._classify_overlap(existing, valid_from, valid_to)
            # Capture state before any mutation (used in audit details).
            snapshot = _version_snapshot(existing)

            if overlap_type == OverlapType.FULL_COVERAGE:
                await self._metadata.delete_version(conn, existing.id)
                audit_entries.append(
                    AuditLogEntry(
                        asset_version_id=existing.id,
                        operation=AuditOperation.FULL_COVERAGE_DELETE,
                        operator_id=operator_id,
                        details=snapshot,
                    )
                )

            elif overlap_type == OverlapType.SPLIT:
                # Replace the original row with two rows that together cover the
                # same window, minus the new version's range. Both inherit the
                # original blob_ref and schema_version (immutable content).
                await self._metadata.delete_version(conn, existing.id)
                left = AssetVersion(
                    satellite_id=existing.satellite_id,
                    asset_type=existing.asset_type,
                    schema_version=existing.schema_version,
                    valid_from=existing.valid_from,
                    valid_to=valid_from,
                    blob_ref=existing.blob_ref,
                )
                # valid_to is not None when SPLIT applies (see _classify_overlap)
                right = AssetVersion(
                    satellite_id=existing.satellite_id,
                    asset_type=existing.asset_type,
                    schema_version=existing.schema_version,
                    valid_from=valid_to,  # type: ignore[arg-type]
                    valid_to=existing.valid_to,
                    blob_ref=existing.blob_ref,
                )
                await self._metadata.insert_version(conn, left)
                await self._metadata.insert_version(conn, right)
                audit_entries.append(
                    AuditLogEntry(
                        asset_version_id=existing.id,
                        operation=AuditOperation.SPLIT,
                        operator_id=operator_id,
                        details=snapshot,
                    )
                )

            else:  # OverlapType.EXTEND (regular or mirrored)
                if existing.valid_from < valid_from:
                    # Regular extend: existing window started before new_from
                    # → close it at new_from.
                    await self._metadata.update_version(
                        conn, existing.id, valid_to=valid_from
                    )
                else:
                    # Mirrored extend: existing window starts inside new window
                    # → push its start forward to new_to (always non-None here).
                    await self._metadata.update_version(
                        conn,
                        existing.id,
                        valid_from=valid_to,  # type: ignore[arg-type]
                    )
                audit_entries.append(
                    AuditLogEntry(
                        asset_version_id=existing.id,
                        operation=AuditOperation.EXTEND,
                        operator_id=operator_id,
                        details=snapshot,
                    )
                )

        return audit_entries

    def _classify_overlap(
        self,
        existing: AssetVersion,
        new_from: datetime,
        new_to: datetime | None,
    ) -> OverlapType:
        e_from = existing.valid_from
        e_to = existing.valid_to

        # New window fully contains existing → remove existing entirely.
        if new_from <= e_from and (
            new_to is None or (e_to is not None and new_to >= e_to)
        ):
            return OverlapType.FULL_COVERAGE

        # Existing starts before new window.
        if e_from < new_from:
            # Existing also extends past the new window's end → SPLIT.
            if new_to is not None and (e_to is None or e_to > new_to):
                return OverlapType.SPLIT
            # Existing ends within new window → truncate its right edge.
            return OverlapType.EXTEND

        # Existing starts inside the new window (new_from <= e_from but not
        # full coverage) → mirrored extend: push existing's left edge forward.
        return OverlapType.EXTEND
