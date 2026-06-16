from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from shared.domain import AssetType, AssetVersion, AuditLogEntry
from shared.repositories._tables import asset_versions, audit_log


def _row_to_asset_version(row: sa.engine.Row) -> AssetVersion:  # type: ignore[type-arg]
    return AssetVersion(
        id=row.id,
        satellite_id=row.satellite_id,
        asset_type=AssetType(row.asset_type),
        schema_version=row.schema_version,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        blob_ref=row.blob_ref,
    )


class AdminMetadataRepository(ABC):
    @abstractmethod
    async def find_overlapping(
        self,
        conn: AsyncConnection,
        satellite_id: str,
        asset_type: AssetType,
        valid_from: datetime,
        valid_to: datetime | None,
    ) -> list[AssetVersion]: ...

    @abstractmethod
    async def insert_version(
        self, conn: AsyncConnection, version: AssetVersion
    ) -> AssetVersion: ...

    @abstractmethod
    async def update_version(
        self,
        conn: AsyncConnection,
        version_id: uuid.UUID,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> AssetVersion: ...

    @abstractmethod
    async def delete_version(
        self, conn: AsyncConnection, version_id: uuid.UUID
    ) -> None: ...

    @abstractmethod
    async def insert_audit_log(
        self, conn: AsyncConnection, entry: AuditLogEntry
    ) -> AuditLogEntry: ...


class AdminMetadataRepositoryPostgres(AdminMetadataRepository):
    async def find_overlapping(
        self,
        conn: AsyncConnection,
        satellite_id: str,
        asset_type: AssetType,
        valid_from: datetime,
        valid_to: datetime | None,
    ) -> list[AssetVersion]:
        # [a,b) overlaps [c,d) iff a < d AND c < b  (None == +∞)
        conditions: list[sa.ColumnElement] = [  # type: ignore[type-arg]
            asset_versions.c.satellite_id == satellite_id,
            asset_versions.c.asset_type == asset_type.value,
            # new_from < existing.valid_to  (or existing is open-ended)
            sa.or_(
                asset_versions.c.valid_to.is_(None),
                asset_versions.c.valid_to > valid_from,
            ),
        ]
        # existing.valid_from < new_to  (only when new window is closed)
        if valid_to is not None:
            conditions.append(asset_versions.c.valid_from < valid_to)

        result = await conn.execute(sa.select(asset_versions).where(*conditions))
        return [_row_to_asset_version(row) for row in result.fetchall()]

    async def insert_version(
        self, conn: AsyncConnection, version: AssetVersion
    ) -> AssetVersion:
        await conn.execute(
            sa.insert(asset_versions).values(
                id=version.id,
                satellite_id=version.satellite_id,
                asset_type=version.asset_type.value,
                schema_version=version.schema_version,
                valid_from=version.valid_from,
                valid_to=version.valid_to,
                blob_ref=version.blob_ref,
            )
        )
        return version

    async def update_version(
        self,
        conn: AsyncConnection,
        version_id: uuid.UUID,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> AssetVersion:
        updates: dict[str, datetime] = {}
        if valid_from is not None:
            updates["valid_from"] = valid_from
        if valid_to is not None:
            updates["valid_to"] = valid_to

        result = await conn.execute(
            sa.update(asset_versions)
            .where(asset_versions.c.id == version_id)
            .values(**updates)
            .returning(*asset_versions.c)
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"AssetVersion {version_id} not found")
        return _row_to_asset_version(row)

    async def delete_version(
        self, conn: AsyncConnection, version_id: uuid.UUID
    ) -> None:
        await conn.execute(
            sa.delete(asset_versions).where(asset_versions.c.id == version_id)
        )

    async def insert_audit_log(
        self, conn: AsyncConnection, entry: AuditLogEntry
    ) -> AuditLogEntry:
        await conn.execute(
            sa.insert(audit_log).values(
                id=entry.id,
                asset_version_id=entry.asset_version_id,
                operation=entry.operation.value,
                operator_id=entry.operator_id,
                occurred_at=entry.occurred_at,
                details=entry.details,
            )
        )
        return entry
