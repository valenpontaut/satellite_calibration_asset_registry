"""Unit tests for cache key helpers — no infrastructure required."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.domain import AssetType
from shared.repositories.cache import (
    bulk_cache_key,
    composite_dataset_version,
    pit_cache_key,
)

UTC = UTC


class TestPitCacheKey:
    def test_format_matches_spec(self) -> None:
        ts = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
        key = pit_cache_key(7, "newsat53", AssetType.DARKFRAME, ts)
        assert key == "v7:newsat53:darkframe:pit:2028-03-15T12:00:00+00:00"

    def test_sub_second_precision_is_truncated(self) -> None:
        ts_micro = datetime(2028, 3, 15, 12, 0, 0, 500_000, tzinfo=UTC)
        ts_trunc = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
        assert pit_cache_key(1, "sat", AssetType.GRAYFRAME, ts_micro) == pit_cache_key(
            1, "sat", AssetType.GRAYFRAME, ts_trunc
        )

    def test_different_dataset_versions_produce_different_keys(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert pit_cache_key(1, "sat", AssetType.DARKFRAME, ts) != pit_cache_key(
            2, "sat", AssetType.DARKFRAME, ts
        )

    def test_different_asset_types_produce_different_keys(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert pit_cache_key(1, "sat", AssetType.DARKFRAME, ts) != pit_cache_key(
            1, "sat", AssetType.GRAYFRAME, ts
        )

    def test_key_contains_satellite_id(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert "newsat99" in pit_cache_key(1, "newsat99", AssetType.DARKFRAME, ts)

    def test_key_contains_asset_type_value(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert "vicarious_cal_gains" in pit_cache_key(
            1, "sat", AssetType.VICARIOUS_CAL_GAINS, ts
        )

    def test_pit_literal_in_key(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert ":pit:" in pit_cache_key(1, "sat", AssetType.DARKFRAME, ts)


class TestBulkCacheKey:
    def test_format_matches_spec(self) -> None:
        ts = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
        key = bulk_cache_key("body_to_payload=1,darkframe=3", "newsat53", ts)
        assert (
            key == "vbody_to_payload=1,darkframe=3:"
            "newsat53:bulk:2028-03-15T12:00:00+00:00"
        )

    def test_sub_second_precision_is_truncated(self) -> None:
        ts_micro = datetime(2028, 1, 1, 0, 0, 0, 999_999, tzinfo=UTC)
        ts_trunc = datetime(2028, 1, 1, tzinfo=UTC)
        assert bulk_cache_key("v=1", "sat", ts_micro) == bulk_cache_key(
            "v=1", "sat", ts_trunc
        )

    def test_different_composite_versions_produce_different_keys(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert bulk_cache_key("darkframe=1,grayframe=1", "sat", ts) != bulk_cache_key(
            "darkframe=2,grayframe=1", "sat", ts
        )

    def test_bulk_literal_in_key(self) -> None:
        ts = datetime(2028, 1, 1, tzinfo=UTC)
        assert ":bulk:" in bulk_cache_key("v=1", "sat", ts)


class TestCompositeDatasetVersion:
    def test_all_four_asset_types_present(self) -> None:
        versions = {at: i for i, at in enumerate(AssetType)}
        composite = composite_dataset_version(versions)
        for at in AssetType:
            assert at.value in composite

    def test_deterministic_regardless_of_dict_insertion_order(self) -> None:
        v1 = {AssetType.DARKFRAME: 1, AssetType.GRAYFRAME: 2}
        v2 = {AssetType.GRAYFRAME: 2, AssetType.DARKFRAME: 1}
        assert composite_dataset_version(v1) == composite_dataset_version(v2)

    def test_sorted_pair_format(self) -> None:
        versions = {AssetType.GRAYFRAME: 5, AssetType.DARKFRAME: 3}
        assert composite_dataset_version(versions) == "darkframe=3,grayframe=5"

    def test_version_change_changes_composite(self) -> None:
        before = {AssetType.DARKFRAME: 1, AssetType.GRAYFRAME: 1}
        after = {AssetType.DARKFRAME: 2, AssetType.GRAYFRAME: 1}
        assert composite_dataset_version(before) != composite_dataset_version(after)

    def test_single_type_composite(self) -> None:
        assert composite_dataset_version({AssetType.DARKFRAME: 42}) == "darkframe=42"
