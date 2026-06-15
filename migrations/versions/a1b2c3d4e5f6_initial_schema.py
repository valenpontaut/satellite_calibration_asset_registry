"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_versions",
        sa.Column("id", sa.UUID, nullable=False),
        sa.Column("satellite_id", sa.Text, nullable=False),
        sa.Column("asset_type", sa.Text, nullable=False),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blob_ref", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_asset_versions_sat_type_temporal",
        "asset_versions",
        ["satellite_id", "asset_type", "valid_from", "valid_to"],
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID, nullable=False),
        # No FK — audit entries must outlive FULL_COVERAGE_DELETE of the referenced row.
        sa.Column("asset_version_id", sa.UUID, nullable=False),
        sa.Column("operation", sa.Text, nullable=False),
        sa.Column("operator_id", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_index("ix_asset_versions_sat_type_temporal", table_name="asset_versions")
    op.drop_table("asset_versions")
