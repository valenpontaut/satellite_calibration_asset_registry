"""Unit tests for AssetResolutionService — no real cache, DB, or storage."""

from __future__ import annotations

import json
import types
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline_api.services.asset_resolution_service import AssetResolutionService
from shared.config import Settings
from shared.domain import AssetType, AssetVersion

# ── constants ─────────────────────────────────────────────────────────────────

T0 = datetime(2028, 1, 1, tzinfo=UTC)
T1 = datetime(2028, 6, 1, tzinfo=UTC)
T2 = datetime(2029, 1, 1, tzinfo=UTC)

SAT = "newsat99"
AT = AssetType.DARKFRAME

SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    redis_url="redis://localhost:6379/0",
    cache_short_ttl_seconds=60,
    cache_long_ttl_seconds=86400,
    presigned_url_expires_in=3600,
)

SHORT_TTL = SETTINGS.cache_short_ttl_seconds  # 60
LONG_TTL = SETTINGS.cache_long_ttl_seconds  # 86400


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_version(
    asset_type: AssetType = AT,
    valid_to: datetime | None = None,
    satellite_id: str = SAT,
) -> AssetVersion:
    return AssetVersion(
        id=uuid.uuid4(),
        satellite_id=satellite_id,
        asset_type=asset_type,
        schema_version="1.0",
        valid_from=T0,
        valid_to=valid_to,
        blob_ref=f"{asset_type}/abc.npy",
    )


# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def parts():
    pipeline_metadata = AsyncMock()
    cache = AsyncMock()
    cache.get_dataset_version.return_value = 1
    cache.get.return_value = None  # cache miss by default
    cache.set.return_value = None

    storage = MagicMock()
    storage.generate_presigned_url.return_value = "https://s3.example.com/presigned"

    service = AssetResolutionService(
        pipeline_metadata=pipeline_metadata,
        cache=cache,
        storage=storage,
        settings=SETTINGS,
    )
    return types.SimpleNamespace(
        service=service,
        pipeline_metadata=pipeline_metadata,
        cache=cache,
        storage=storage,
    )


# ── test 1: resolve_point_in_time — cache hit ─────────────────────────────────


async def test_resolve_pit_cache_hit_returns_cached_value_without_db_lookup(parts):
    cached_payload = {"found": True, "presigned_url": "https://s3/x", "x": "y"}
    parts.cache.get.return_value = json.dumps(cached_payload)

    result = await parts.service.resolve_point_in_time(SAT, AT, T0)

    parts.pipeline_metadata.find_point_in_time.assert_not_called()
    assert result == cached_payload


# ── test 2: cache miss, found, open-ended → short TTL ────────────────────────


async def test_resolve_pit_cache_miss_found_open_ended_calls_db_and_uses_short_ttl(
    parts,
):
    version = _make_version(valid_to=None)  # open-ended
    parts.pipeline_metadata.find_point_in_time.return_value = version

    result = await parts.service.resolve_point_in_time(SAT, AT, T0)

    parts.pipeline_metadata.find_point_in_time.assert_called_once_with(SAT, AT, T0)
    _, _, ttl = parts.cache.set.call_args.args
    assert ttl == SHORT_TTL
    assert result["found"] is True
    assert "presigned_url" in result
    assert "asset_version" in result


# ── test 3: cache miss, found, closed window → long TTL ──────────────────────


async def test_resolve_pit_cache_miss_found_closed_window_uses_long_ttl(parts):
    version = _make_version(valid_to=T1)  # closed historical window
    parts.pipeline_metadata.find_point_in_time.return_value = version

    await parts.service.resolve_point_in_time(SAT, AT, T0)

    _, _, ttl = parts.cache.set.call_args.args
    assert ttl == LONG_TTL


# ── test 4: cache miss, not found → short TTL + structured not-found response ─


async def test_resolve_pit_cache_miss_not_found_uses_short_ttl_and_structured_response(
    parts,
):
    parts.pipeline_metadata.find_point_in_time.return_value = None

    result = await parts.service.resolve_point_in_time(SAT, AT, T0)

    _, _, ttl = parts.cache.set.call_args.args
    assert ttl == SHORT_TTL
    assert result["found"] is False
    assert result["satellite_id"] == SAT
    assert result["asset_type"] == str(AT)
    assert "timestamp" in result


# ── test 5: resolve_bulk — one entry per AssetType ───────────────────────────


async def test_resolve_bulk_returns_exactly_one_entry_per_asset_type(parts):
    found_version = _make_version(valid_to=T1)
    parts.pipeline_metadata.find_bulk.return_value = {
        at: found_version if at == AT else None for at in AssetType
    }

    result = await parts.service.resolve_bulk(SAT, T0)

    assert len(result) == len(AssetType)
    assert result[str(AT)]["found"] is True
    assert "presigned_url" in result[str(AT)]
    for at in AssetType:
        if at != AT:
            assert result[str(at)]["found"] is False
            assert result[str(at)]["satellite_id"] == SAT


# ── test 6a: resolve_bulk TTL — any open-ended version → short TTL ────────────


async def test_resolve_bulk_ttl_is_short_when_any_version_is_open_ended(parts):
    open_version = _make_version(asset_type=AssetType.DARKFRAME, valid_to=None)
    closed_version = _make_version(asset_type=AssetType.GRAYFRAME, valid_to=T1)
    parts.pipeline_metadata.find_bulk.return_value = {
        AssetType.DARKFRAME: open_version,
        AssetType.GRAYFRAME: closed_version,
        AssetType.VICARIOUS_CAL_GAINS: None,
        AssetType.BODY_TO_PAYLOAD: None,
    }

    await parts.service.resolve_bulk(SAT, T0)

    _, _, ttl = parts.cache.set.call_args.args
    assert ttl == SHORT_TTL


# ── test 6b: resolve_bulk TTL — all closed → long TTL ────────────────────────


async def test_resolve_bulk_ttl_is_long_when_all_found_versions_are_closed(parts):
    closed_dark = _make_version(asset_type=AssetType.DARKFRAME, valid_to=T1)
    closed_gray = _make_version(asset_type=AssetType.GRAYFRAME, valid_to=T1)
    parts.pipeline_metadata.find_bulk.return_value = {
        AssetType.DARKFRAME: closed_dark,
        AssetType.GRAYFRAME: closed_gray,
        AssetType.VICARIOUS_CAL_GAINS: None,
        AssetType.BODY_TO_PAYLOAD: None,
    }

    await parts.service.resolve_bulk(SAT, T0)

    _, _, ttl = parts.cache.set.call_args.args
    assert ttl == LONG_TTL


# ── test 7: _build_cache_key — exact pit format ───────────────────────────────


def test_build_cache_key_pit_format_matches_spec(parts):
    ts = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
    key = parts.service._build_cache_key("newsat53", AssetType.DARKFRAME, 7, ts)
    assert key == "v7:newsat53:darkframe:pit:2028-03-15T12:00:00+00:00"


def test_build_cache_key_pit_sub_second_precision_is_truncated(parts):
    ts_micro = datetime(2028, 3, 15, 12, 0, 0, 999_000, tzinfo=UTC)
    ts_trunc = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
    assert parts.service._build_cache_key(
        "sat", AssetType.DARKFRAME, 1, ts_micro
    ) == parts.service._build_cache_key("sat", AssetType.DARKFRAME, 1, ts_trunc)


# ── test 8: _build_cache_key — exact bulk format ──────────────────────────────


def test_build_cache_key_bulk_format_matches_spec(parts):
    ts = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
    composite = "body_to_payload=1,darkframe=3,grayframe=2,vicarious_cal_gains=4"
    key = parts.service._build_cache_key("newsat53", None, composite, ts, bulk=True)
    assert key == f"v{composite}:newsat53:bulk:2028-03-15T12:00:00+00:00"


def test_build_cache_key_bulk_sub_second_precision_is_truncated(parts):
    ts_micro = datetime(2028, 3, 15, 12, 0, 0, 500_000, tzinfo=UTC)
    ts_trunc = datetime(2028, 3, 15, 12, 0, 0, tzinfo=UTC)
    assert parts.service._build_cache_key(
        "sat", None, "darkframe=1", ts_micro, bulk=True
    ) == parts.service._build_cache_key("sat", None, "darkframe=1", ts_trunc, bulk=True)
