from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from shared.domain import AssetType, AssetVersion
from shared.repositories._tables import asset_versions


def _active_at(ts: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        asset_versions.c.valid_from <= ts,
        sa.or_(
            asset_versions.c.valid_to.is_(None),
            asset_versions.c.valid_to > ts,
        ),
    )


def _row_to_asset_version(row: sa.engine.Row) -> AssetVersion:
    return AssetVersion(
        id=row.id,
        satellite_id=row.satellite_id,
        asset_type=AssetType(row.asset_type),
        schema_version=row.schema_version,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        blob_ref=row.blob_ref,
    )


class PipelineMetadataRepository(ABC):
    @abstractmethod
    async def find_point_in_time(
        self,
        satellite_id: str,
        asset_type: AssetType,
        timestamp: datetime,
    ) -> AssetVersion | None: ...

    @abstractmethod
    async def find_bulk(
        self,
        satellite_id: str,
        timestamp: datetime,
    ) -> dict[AssetType, AssetVersion | None]: ...


class PipelineMetadataRepositoryPostgres(PipelineMetadataRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def find_point_in_time(
        self,
        satellite_id: str,
        asset_type: AssetType,
        timestamp: datetime,
    ) -> AssetVersion | None:
        query = (
            sa.select(asset_versions)
            .where(
                asset_versions.c.satellite_id == satellite_id,
                asset_versions.c.asset_type == asset_type.value,
                _active_at(timestamp),
            )
            .limit(1)
        )

        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).fetchone()

        return _row_to_asset_version(row._mapping) if row else None

    async def find_bulk(
        self,
        satellite_id: str,
        timestamp: datetime,
    ) -> dict[AssetType, AssetVersion | None]:
        query = sa.select(asset_versions).where(
            asset_versions.c.satellite_id == satellite_id,
            _active_at(timestamp),
        )

        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).fetchall()

        found: dict[AssetType, AssetVersion] = {
            AssetType(row._mapping["asset_type"]): _row_to_asset_version(row._mapping)
            for row in rows
        }

        return {asset_type: found.get(asset_type) for asset_type in AssetType}
