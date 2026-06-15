"""SQLAlchemy Core table definitions shared by repositories and Alembic."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

metadata = MetaData()

asset_versions = sa.Table(
    "asset_versions",
    metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("satellite_id", sa.Text, nullable=False),
    sa.Column("asset_type", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
    sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    sa.Column("blob_ref", sa.Text, nullable=False),
    sa.Index(
        "ix_asset_versions_sat_type_temporal",
        "satellite_id",
        "asset_type",
        "valid_from",
        "valid_to",
    ),
)

# No FK constraint on asset_version_id: audit entries must survive
# FULL_COVERAGE_DELETE, which removes rows from asset_versions.
audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("asset_version_id", PGUUID(as_uuid=True), nullable=False),
    sa.Column("operation", sa.Text, nullable=False),
    sa.Column("operator_id", sa.Text, nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("details", JSONB, nullable=False),
)
