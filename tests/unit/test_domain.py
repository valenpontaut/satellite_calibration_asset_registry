"""Unit tests for shared.domain — temporal correctness focus."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from shared.domain import (
    AssetDefinition,
    AssetType,
    AssetVersion,
    AuditLogEntry,
    AuditOperation,
    OverlapType,
    StorageFormat,
)

UTC = timezone.utc

T0 = datetime(2028, 1, 1, tzinfo=UTC)
T1 = datetime(2028, 6, 1, tzinfo=UTC)
T2 = datetime(2029, 1, 1, tzinfo=UTC)


def make_version(
    valid_from: datetime,
    valid_to: datetime | None = None,
    *,
    satellite_id: str = "newsat53",
    asset_type: AssetType = AssetType.DARKFRAME,
) -> AssetVersion:
    return AssetVersion(
        satellite_id=satellite_id,
        asset_type=asset_type,
        schema_version="1.0",
        valid_from=valid_from,
        valid_to=valid_to,
        blob_ref="scar-assets/newsat53/darkframe/abc123.npy",
    )


# ── is_valid_at: open-ended window (valid_to=None) ──────────────────────────


class TestIsValidAtOpenEnded:
    def test_at_valid_from_is_included(self) -> None:
        assert make_version(T0).is_valid_at(T0) is True

    def test_after_valid_from_is_valid(self) -> None:
        assert make_version(T0).is_valid_at(T1) is True

    def test_far_future_is_valid(self) -> None:
        assert make_version(T0).is_valid_at(datetime(2099, 12, 31, tzinfo=UTC)) is True

    def test_one_second_before_valid_from_is_not_valid(self) -> None:
        assert make_version(T0).is_valid_at(T0 - timedelta(seconds=1)) is False

    def test_one_microsecond_before_valid_from_is_not_valid(self) -> None:
        assert make_version(T0).is_valid_at(T0 - timedelta(microseconds=1)) is False


# ── is_valid_at: closed window [valid_from, valid_to) ───────────────────────


class TestIsValidAtClosedWindow:
    def test_at_valid_from_is_included(self) -> None:
        assert make_version(T0, T1).is_valid_at(T0) is True

    def test_strictly_inside_window_is_valid(self) -> None:
        midpoint = T0 + (T1 - T0) / 2
        assert make_version(T0, T1).is_valid_at(midpoint) is True

    def test_one_second_before_valid_to_is_valid(self) -> None:
        assert make_version(T0, T1).is_valid_at(T1 - timedelta(seconds=1)) is True

    def test_at_valid_to_is_excluded(self) -> None:
        """Half-open interval: valid_to boundary is not part of the window."""
        assert make_version(T0, T1).is_valid_at(T1) is False

    def test_one_second_after_valid_to_is_not_valid(self) -> None:
        assert make_version(T0, T1).is_valid_at(T1 + timedelta(seconds=1)) is False

    def test_one_second_before_valid_from_is_not_valid(self) -> None:
        assert make_version(T0, T1).is_valid_at(T0 - timedelta(seconds=1)) is False

    def test_single_second_window_exact_bounds(self) -> None:
        """[T0, T0+1s): T0 included, T0+1s excluded."""
        window_end = T0 + timedelta(seconds=1)
        v = make_version(T0, window_end)
        assert v.is_valid_at(T0) is True
        assert v.is_valid_at(window_end) is False

    def test_zero_duration_window_is_never_valid(self) -> None:
        """[T0, T0) is an empty interval — no timestamp can satisfy it."""
        v = make_version(T0, T0)
        assert v.is_valid_at(T0) is False
        assert v.is_valid_at(T0 - timedelta(microseconds=1)) is False
        assert v.is_valid_at(T0 + timedelta(microseconds=1)) is False


# ── timezone enforcement ─────────────────────────────────────────────────────


class TestTimezoneEnforcement:
    def test_naive_timestamp_in_is_valid_at_raises(self) -> None:
        v = make_version(T0, T1)
        with pytest.raises(ValueError, match="timezone-aware"):
            v.is_valid_at(datetime(2028, 3, 1))

    def test_naive_valid_from_in_constructor_raises(self) -> None:
        with pytest.raises(ValidationError):
            make_version(datetime(2028, 1, 1))

    def test_naive_valid_to_in_constructor_raises(self) -> None:
        with pytest.raises(ValidationError):
            make_version(T0, datetime(2028, 6, 1))


# ── AssetVersion model defaults ──────────────────────────────────────────────


class TestAssetVersionDefaults:
    def test_id_is_auto_assigned_uuid(self) -> None:
        v = make_version(T0)
        assert isinstance(v.id, uuid.UUID)

    def test_two_instances_have_distinct_ids(self) -> None:
        assert make_version(T0).id != make_version(T0).id

    def test_valid_to_defaults_to_none(self) -> None:
        assert make_version(T0).valid_to is None

    def test_explicit_id_is_preserved(self) -> None:
        fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
        v = AssetVersion(
            id=fixed,
            satellite_id="newsat53",
            asset_type=AssetType.DARKFRAME,
            schema_version="1.0",
            valid_from=T0,
            blob_ref="some/ref.npy",
        )
        assert v.id == fixed


# ── enums ────────────────────────────────────────────────────────────────────


class TestEnums:
    def test_all_four_asset_types(self) -> None:
        assert {t.value for t in AssetType} == {
            "darkframe",
            "grayframe",
            "vicarious_cal_gains",
            "body_to_payload",
        }

    def test_storage_formats(self) -> None:
        assert {f.value for f in StorageFormat} == {"npy", "json"}

    def test_audit_operations(self) -> None:
        assert {o.value for o in AuditOperation} == {
            "CREATE",
            "EXTEND",
            "SPLIT",
            "FULL_COVERAGE_DELETE",
            "RETIRE",
        }

    def test_overlap_types(self) -> None:
        assert {t.value for t in OverlapType} == {"EXTEND", "SPLIT", "FULL_COVERAGE"}

    def test_asset_type_is_str_comparable(self) -> None:
        assert AssetType.DARKFRAME == "darkframe"
        assert AssetType.VICARIOUS_CAL_GAINS == "vicarious_cal_gains"

    def test_overlap_type_and_audit_operation_are_distinct_enum_types(self) -> None:
        """EXTEND appears in both enums but models a different concept in each."""
        assert type(OverlapType.EXTEND) is OverlapType
        assert type(AuditOperation.EXTEND) is AuditOperation
        assert OverlapType.EXTEND is not AuditOperation.EXTEND


# ── AuditLogEntry ────────────────────────────────────────────────────────────


class TestAuditLogEntry:
    def test_id_auto_assigned(self) -> None:
        entry = AuditLogEntry(
            asset_version_id=uuid.uuid4(),
            operation=AuditOperation.CREATE,
            operator_id="alice",
            details={
                "asset_type": "darkframe",
                "valid_from": "2028-01-01T00:00:00+00:00",
                "valid_to": None,
                "blob_ref": "scar-assets/x.npy",
                "schema_version": "1.0",
            },
        )
        assert isinstance(entry.id, uuid.UUID)

    def test_occurred_at_is_timezone_aware(self) -> None:
        entry = AuditLogEntry(
            asset_version_id=uuid.uuid4(),
            operation=AuditOperation.RETIRE,
            operator_id="bob",
            details={},
        )
        assert entry.occurred_at.tzinfo is not None

    def test_two_entries_have_distinct_ids(self) -> None:
        kwargs = dict(
            asset_version_id=uuid.uuid4(),
            operation=AuditOperation.CREATE,
            operator_id="carol",
            details={},
        )
        assert AuditLogEntry(**kwargs).id != AuditLogEntry(**kwargs).id


# ── AssetDefinition ──────────────────────────────────────────────────────────


class TestAssetDefinition:
    def test_darkframe_definition(self) -> None:
        d = AssetDefinition(
            asset_type=AssetType.DARKFRAME,
            schema_version="1.0",
            storage_format=StorageFormat.NPY,
        )
        assert d.asset_type == AssetType.DARKFRAME
        assert d.storage_format == StorageFormat.NPY

    def test_json_asset_definition(self) -> None:
        d = AssetDefinition(
            asset_type=AssetType.VICARIOUS_CAL_GAINS,
            schema_version="1.0",
            storage_format=StorageFormat.JSON,
            description="Per-band scale/bias factors",
        )
        assert d.storage_format == StorageFormat.JSON
        assert d.description == "Per-band scale/bias factors"

    def test_description_defaults_to_empty_string(self) -> None:
        d = AssetDefinition(
            asset_type=AssetType.BODY_TO_PAYLOAD,
            schema_version="1.0",
            storage_format=StorageFormat.JSON,
        )
        assert d.description == ""
