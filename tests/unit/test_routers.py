"""Unit tests for admin_api and pipeline_api routers via FastAPI TestClient."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api.routers.assets import router as admin_router
from pipeline_api.routers.assets import router as pipeline_router
from shared.domain import AssetType, AssetVersion
from shared.validation.validators import AssetValidationError

# ── constants ─────────────────────────────────────────────────────────────────

SAT = "newsat99"
T0 = datetime(2028, 1, 1, tzinfo=UTC)
T1 = datetime(2028, 6, 1, tzinfo=UTC)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_version(
    asset_type: AssetType = AssetType.DARKFRAME,
    valid_to: datetime | None = None,
) -> AssetVersion:
    return AssetVersion(
        id=uuid.uuid4(),
        satellite_id=SAT,
        asset_type=asset_type,
        schema_version="1.0",
        valid_from=T0,
        valid_to=valid_to,
        blob_ref=f"{asset_type}/abc.npy",
    )


def _admin_client(mock_service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    app.state.service = mock_service
    return TestClient(app)


def _pipeline_client(mock_service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(pipeline_router)
    app.state.service = mock_service
    return TestClient(app)


def _post_asset(client: TestClient, asset_type: str = "darkframe") -> object:
    return client.post(
        "/assets",
        data={
            "satellite_id": SAT,
            "asset_type": asset_type,
            "valid_from": "2028-01-01T00:00:00+00:00",
            "operator_id": "test-operator",
        },
        files={"file": ("frame.npy", b"fake-npy-bytes", "application/octet-stream")},
    )


# ── admin API ─────────────────────────────────────────────────────────────────


def test_admin_create_asset_returns_201_with_version_payload():
    version = _make_version()
    svc = AsyncMock()
    svc.create_asset_version.return_value = version
    client = _admin_client(svc)

    response = _post_asset(client)

    assert response.status_code == 201
    body = response.json()
    assert body["satellite_id"] == SAT
    assert body["asset_type"] == "darkframe"
    assert "id" in body
    assert "valid_from" in body


def test_admin_create_asset_invalid_asset_type_returns_422():
    svc = AsyncMock()
    client = _admin_client(svc)

    response = _post_asset(client, asset_type="not_a_real_type")

    assert response.status_code == 422


def test_admin_create_asset_validation_error_from_service_returns_422():
    svc = AsyncMock()
    svc.create_asset_version.side_effect = AssetValidationError(
        "array must be 2D float"
    )
    client = _admin_client(svc)

    response = _post_asset(client)

    assert response.status_code == 422
    assert "array must be 2D float" in response.json()["detail"]


def test_admin_retire_asset_returns_200_with_updated_version():
    version = _make_version(valid_to=T1)
    svc = AsyncMock()
    svc.retire_asset_version.return_value = version
    client = _admin_client(svc)

    _body = {"retired_at": "2028-06-01T00:00:00+00:00", "operator_id": "test-operator"}
    response = client.request(
        "DELETE",
        f"/assets/{uuid.uuid4()}/retire",
        json=_body,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["satellite_id"] == SAT
    assert body["asset_type"] == "darkframe"
    assert body["valid_to"] is not None


def test_admin_retire_asset_not_found_returns_404():
    svc = AsyncMock()
    svc.retire_asset_version.side_effect = ValueError("AssetVersion xyz not found")
    client = _admin_client(svc)

    _body = {"retired_at": "2028-06-01T00:00:00+00:00", "operator_id": "test-operator"}
    response = client.request(
        "DELETE",
        f"/assets/{uuid.uuid4()}/retire",
        json=_body,
    )

    assert response.status_code == 404


def test_admin_health_returns_ok():
    client = _admin_client(AsyncMock())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── pipeline API ──────────────────────────────────────────────────────────────


def test_pipeline_resolve_pit_found_returns_200_with_presigned_url():
    version = _make_version()
    found_result = {
        "found": True,
        "asset_version": version.model_dump(mode="json"),
        "presigned_url": "https://s3.example.com/presigned",
    }
    svc = AsyncMock()
    svc.resolve_point_in_time.return_value = found_result
    client = _pipeline_client(svc)

    response = client.get(
        "/resolve",
        params={
            "satellite_id": SAT,
            "asset_type": "darkframe",
            "timestamp": "2028-03-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert "presigned_url" in body
    assert "asset_version" in body


def test_pipeline_resolve_pit_not_found_returns_200_with_found_false():
    not_found_result = {
        "found": False,
        "satellite_id": SAT,
        "asset_type": "darkframe",
        "timestamp": "2028-03-01T00:00:00+00:00",
    }
    svc = AsyncMock()
    svc.resolve_point_in_time.return_value = not_found_result
    client = _pipeline_client(svc)

    response = client.get(
        "/resolve",
        params={
            "satellite_id": SAT,
            "asset_type": "darkframe",
            "timestamp": "2028-03-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["satellite_id"] == SAT


def test_pipeline_resolve_bulk_returns_200_with_one_entry_per_asset_type():
    bulk_result = {
        str(at): (
            {
                "found": True,
                "asset_version": _make_version(asset_type=at).model_dump(mode="json"),
                "presigned_url": "https://s3.example.com/presigned",
            }
            if at == AssetType.DARKFRAME
            else {
                "found": False,
                "satellite_id": SAT,
                "asset_type": str(at),
                "timestamp": "2028-03-01T00:00:00+00:00",
            }
        )
        for at in AssetType
    }
    svc = AsyncMock()
    svc.resolve_bulk.return_value = bulk_result
    client = _pipeline_client(svc)

    response = client.get(
        "/resolve/bulk",
        params={"satellite_id": SAT, "timestamp": "2028-03-01T00:00:00+00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(AssetType)
    assert body[str(AssetType.DARKFRAME)]["found"] is True


def test_pipeline_health_returns_ok():
    client = _pipeline_client(AsyncMock())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
