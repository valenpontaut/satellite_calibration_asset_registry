"""Unit tests for AssetAdminService — no real DB, storage, or cache."""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from admin_api.services.asset_admin_service import AssetAdminService
from shared.domain import AssetType, AssetVersion, AuditOperation, StorageFormat
from shared.validation.service import ValidatedAsset
from shared.validation.validators import AssetValidationError

# ── constants ─────────────────────────────────────────────────────────────────

T0 = datetime(2027, 1, 1, tzinfo=UTC)
T1 = datetime(2028, 1, 1, tzinfo=UTC)
T2 = datetime(2028, 6, 1, tzinfo=UTC)
T3 = datetime(2029, 1, 1, tzinfo=UTC)

SAT = "newsat80"
AT = AssetType.DARKFRAME
FILE_CONTENT = b"fake-npy-bytes"
OPERATOR = "ops-team"
BLOB_REF = "darkframe/new-upload.npy"
EXISTING_BLOB_REF = "darkframe/existing.npy"

VALIDATED = ValidatedAsset(
    asset_type=AT, schema_version="1.0", storage_format=StorageFormat.NPY
)

_PATCH_BLOB_REF = "admin_api.services.asset_admin_service.generate_blob_ref"


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_version(
    valid_from: datetime = T1,
    valid_to: datetime | None = None,
    blob_ref: str = EXISTING_BLOB_REF,
    version_id: uuid.UUID | None = None,
) -> AssetVersion:
    return AssetVersion(
        id=version_id or uuid.uuid4(),
        satellite_id=SAT,
        asset_type=AT,
        schema_version="1.0",
        valid_from=valid_from,
        valid_to=valid_to,
        blob_ref=blob_ref,
    )


def _make_engine(conn: AsyncMock) -> MagicMock:
    engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    engine.begin.return_value = cm
    return engine


# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def parts():
    """Fresh mocks for each test — no real infrastructure."""
    conn = AsyncMock()
    validation = MagicMock()
    validation.validate.return_value = VALIDATED

    metadata = AsyncMock()
    metadata.find_overlapping.return_value = []
    metadata.insert_version.return_value = None
    metadata.update_version.return_value = _make_version()
    metadata.delete_version.return_value = None
    metadata.insert_audit_log.return_value = None

    storage = MagicMock()
    storage.put_object.return_value = BLOB_REF

    cache = AsyncMock()
    cache.incr_dataset_version.return_value = 1

    service = AssetAdminService(
        validation_service=validation,
        metadata_repo=metadata,
        storage_repo=storage,
        cache_repo=cache,
        engine=_make_engine(conn),
    )
    return types.SimpleNamespace(
        service=service,
        validation=validation,
        metadata=metadata,
        storage=storage,
        cache=cache,
        conn=conn,
    )


# ── test 1: create — no overlaps (first insertion) ────────────────────────────


async def test_create_no_overlaps_validate_called_with_asset_type_and_content(parts):
    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.validation.validate.assert_called_once_with(AT, FILE_CONTENT)


async def test_create_no_overlaps_put_object_called_before_any_metadata_method(parts):
    call_order: list[str] = []

    parts.storage.put_object.side_effect = lambda k, c: call_order.append("put_object")

    async def _track_find(conn, sat, at, vf, vt):
        call_order.append("find_overlapping")
        return []

    async def _track_insert(conn, version):
        call_order.append("insert_version")

    parts.metadata.find_overlapping.side_effect = _track_find
    parts.metadata.insert_version.side_effect = _track_insert

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    assert "put_object" in call_order
    assert "find_overlapping" in call_order
    assert call_order.index("put_object") < call_order.index("find_overlapping")
    assert call_order.index("put_object") < call_order.index("insert_version")


async def test_create_no_overlaps_insert_version_called_with_correct_fields(parts):
    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.metadata.insert_version.assert_called_once()
    version = parts.metadata.insert_version.call_args.args[1]
    assert version.satellite_id == SAT
    assert version.asset_type == AT
    assert version.schema_version == "1.0"
    assert version.valid_from == T1
    assert version.valid_to is None
    assert version.blob_ref == BLOB_REF


async def test_create_no_overlaps_audit_log_called_once_with_create_operation(parts):
    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.metadata.insert_audit_log.assert_called_once()
    entry = parts.metadata.insert_audit_log.call_args.args[1]
    assert entry.operation == AuditOperation.CREATE
    assert entry.operator_id == OPERATOR


async def test_create_no_overlaps_incr_dataset_version_called_once_post_commit(parts):
    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.cache.incr_dataset_version.assert_called_once_with(SAT, AT)


async def test_create_no_overlaps_returns_asset_version(parts):
    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        result = await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    assert isinstance(result, AssetVersion)
    assert result.satellite_id == SAT
    assert result.asset_type == AT


# ── test 2: create — EXTEND (existing open-ended row, new version starts after) ──


async def test_create_extend_truncates_existing_valid_to_at_new_from(parts):
    existing = _make_version(valid_from=T0, valid_to=None)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.metadata.update_version.assert_called_once_with(
        parts.conn, existing.id, valid_to=T1
    )


async def test_create_extend_audit_log_called_twice_with_extend_and_create(parts):
    existing = _make_version(valid_from=T0, valid_to=None)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.insert_audit_log.call_count == 2
    ops = [c.args[1].operation for c in parts.metadata.insert_audit_log.call_args_list]
    assert AuditOperation.EXTEND in ops
    assert AuditOperation.CREATE in ops


async def test_create_extend_incr_dataset_version_called_exactly_once(parts):
    existing = _make_version(valid_from=T0, valid_to=None)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, None, FILE_CONTENT, OPERATOR
        )

    parts.cache.incr_dataset_version.assert_called_once_with(SAT, AT)


# ── test 3: create —
# MIRRORED EXTEND (new has explicit valid_to, existing starts inside) ─


async def test_create_mirrored_extend_pushes_existing_valid_from_to_new_to(parts):
    # New: [T0, T2), Existing: [T1, None) — existing starts inside new window.
    existing = _make_version(valid_from=T1, valid_to=None)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T0, T2, FILE_CONTENT, OPERATOR
        )

    parts.metadata.update_version.assert_called_once_with(
        parts.conn, existing.id, valid_from=T2
    )


async def test_create_mirrored_extend_audit_log_called_twice_with_extend_and_create(
    parts,
):
    existing = _make_version(valid_from=T1, valid_to=None)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T0, T2, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.insert_audit_log.call_count == 2
    ops = [c.args[1].operation for c in parts.metadata.insert_audit_log.call_args_list]
    assert AuditOperation.EXTEND in ops
    assert AuditOperation.CREATE in ops


# ── test 4: create — SPLIT (new version falls inside existing) ────────────────


async def test_create_split_deletes_existing_and_inserts_three_versions(parts):
    # New: [T1, T2), Existing: [T0, T3) — new falls strictly inside existing.
    existing = _make_version(valid_from=T0, valid_to=T3, blob_ref=EXISTING_BLOB_REF)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T2, FILE_CONTENT, OPERATOR
        )

    parts.metadata.delete_version.assert_called_once_with(parts.conn, existing.id)
    assert parts.metadata.insert_version.call_count == 3


async def test_create_split_two_halves_share_original_blob_ref(parts):
    existing = _make_version(valid_from=T0, valid_to=T3, blob_ref=EXISTING_BLOB_REF)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T2, FILE_CONTENT, OPERATOR
        )

    calls = parts.metadata.insert_version.call_args_list
    left, right, _ = [c.args[1] for c in calls]
    assert left.blob_ref == EXISTING_BLOB_REF
    assert right.blob_ref == EXISTING_BLOB_REF
    assert left.valid_from == T0
    assert left.valid_to == T1
    assert right.valid_from == T2
    assert right.valid_to == T3


async def test_create_split_audit_log_called_twice_with_split_and_create(parts):
    existing = _make_version(valid_from=T0, valid_to=T3)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T2, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.insert_audit_log.call_count == 2
    ops = [c.args[1].operation for c in parts.metadata.insert_audit_log.call_args_list]
    assert AuditOperation.SPLIT in ops
    assert AuditOperation.CREATE in ops


# ── test 5: create — FULL_COVERAGE (new version covers existing entirely) ─────


async def test_create_full_coverage_deletes_existing_version(parts):
    # New: [T0, None), Existing: [T1, T2) — fully contained by new window.
    existing = _make_version(valid_from=T1, valid_to=T2)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T0, None, FILE_CONTENT, OPERATOR
        )

    parts.metadata.delete_version.assert_called_once_with(parts.conn, existing.id)


async def test_audit_log_called_twice_on_full_coverage_replace(
    parts,
):
    existing = _make_version(valid_from=T1, valid_to=T2)
    parts.metadata.find_overlapping.return_value = [existing]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T0, None, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.insert_audit_log.call_count == 2
    ops = [c.args[1].operation for c in parts.metadata.insert_audit_log.call_args_list]
    assert AuditOperation.FULL_COVERAGE_DELETE in ops
    assert AuditOperation.CREATE in ops


# ── test 6: create — multi-overlap (2 existing rows) ─────────────────────────


async def test_create_multi_overlap_two_rows_each_classified_and_mutated_independently(
    parts,
):
    # New: [T1, T3)
    # Row A: [T0, T2) → e_from < new_from, e_to < new_to → regular EXTEND
    # Row B: [T2, None) → e_from >= new_from, not full coverage → mirrored EXTEND
    row_a = _make_version(valid_from=T0, valid_to=T2, blob_ref="darkframe/row-a.npy")
    row_b = _make_version(valid_from=T2, valid_to=None, blob_ref="darkframe/row-b.npy")
    parts.metadata.find_overlapping.return_value = [row_a, row_b]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T3, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.update_version.call_count == 2


async def test_create_multi_overlap_audit_log_called_three_times(parts):
    row_a = _make_version(valid_from=T0, valid_to=T2, blob_ref="darkframe/row-a.npy")
    row_b = _make_version(valid_from=T2, valid_to=None, blob_ref="darkframe/row-b.npy")
    parts.metadata.find_overlapping.return_value = [row_a, row_b]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T3, FILE_CONTENT, OPERATOR
        )

    assert parts.metadata.insert_audit_log.call_count == 3
    ops = [c.args[1].operation for c in parts.metadata.insert_audit_log.call_args_list]
    assert ops.count(AuditOperation.EXTEND) == 2
    assert AuditOperation.CREATE in ops


async def test_create_multi_overlap_incr_dataset_version_called_exactly_once(parts):
    row_a = _make_version(valid_from=T0, valid_to=T2, blob_ref="darkframe/row-a.npy")
    row_b = _make_version(valid_from=T2, valid_to=None, blob_ref="darkframe/row-b.npy")
    parts.metadata.find_overlapping.return_value = [row_a, row_b]

    with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
        await parts.service.create_asset_version(
            SAT, AT, T1, T3, FILE_CONTENT, OPERATOR
        )

    parts.cache.incr_dataset_version.assert_called_once_with(SAT, AT)


# ── test 7: create — validation failure ───────────────────────────────────────


async def test_create_validation_error_prevents_storage_and_all_metadata_calls(parts):
    parts.validation.validate.side_effect = AssetValidationError("bad array dtype")

    with pytest.raises(AssetValidationError):
        with patch(_PATCH_BLOB_REF, return_value=BLOB_REF):
            await parts.service.create_asset_version(
                SAT, AT, T1, None, FILE_CONTENT, OPERATOR
            )

    parts.storage.put_object.assert_not_called()
    parts.metadata.find_overlapping.assert_not_called()
    parts.metadata.insert_version.assert_not_called()
    parts.metadata.update_version.assert_not_called()
    parts.metadata.delete_version.assert_not_called()
    parts.metadata.insert_audit_log.assert_not_called()
    parts.cache.incr_dataset_version.assert_not_called()


# ── test 8: retire ────────────────────────────────────────────────────────────


async def test_retire_asset_version_updates_valid_to_and_inserts_retire_audit_log(
    parts,
):
    version_id = uuid.uuid4()
    retired_at = T2

    mock_row = MagicMock()
    mock_row.id = version_id
    mock_row.satellite_id = SAT
    mock_row.asset_type = "darkframe"
    mock_row.schema_version = "1.0"
    mock_row.valid_from = T0
    mock_row.valid_to = None
    mock_row.blob_ref = EXISTING_BLOB_REF

    exec_result = MagicMock()
    exec_result.fetchone.return_value = mock_row
    parts.conn.execute = AsyncMock(return_value=exec_result)

    retired_version = _make_version(valid_from=T0, valid_to=retired_at)
    parts.metadata.update_version.return_value = retired_version

    result = await parts.service.retire_asset_version(
        version_id=version_id, retired_at=retired_at, operator_id=OPERATOR
    )

    parts.metadata.update_version.assert_called_once_with(
        parts.conn, version_id, valid_to=retired_at
    )
    parts.metadata.insert_audit_log.assert_called_once()
    entry = parts.metadata.insert_audit_log.call_args.args[1]
    assert entry.operation == AuditOperation.RETIRE
    assert entry.operator_id == OPERATOR
    parts.cache.incr_dataset_version.assert_called_once_with(SAT, AT)
    assert result == retired_version
