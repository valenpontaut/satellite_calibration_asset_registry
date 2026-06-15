"""Unit tests for shared.validation — validator correctness and registry wiring."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from shared.domain import AssetType, StorageFormat
from shared.validation import (
    AssetDefinitionRegistry,
    AssetValidationError,
    AssetValidationService,
    AssetValidator,
    BodyToPayloadJsonValidator,
    Npy2DFloatArrayValidator,
    UnknownAssetTypeError,
    ValidatedAsset,
    VicariousCalGainsJsonValidator,
)

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


# ── helpers ──────────────────────────────────────────────────────────────────


def npy_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


def valid_2d_float32() -> bytes:
    return npy_bytes(np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))


def valid_2d_float64() -> bytes:
    return npy_bytes(np.zeros((64, 64), dtype=np.float64))


# ── Npy2DFloatArrayValidator ─────────────────────────────────────────────────


class TestNpy2DFloatArrayValidator:
    def setup_method(self) -> None:
        self.v = Npy2DFloatArrayValidator()

    def test_valid_2d_float32_passes(self) -> None:
        self.v.validate(valid_2d_float32())

    def test_valid_2d_float64_passes(self) -> None:
        self.v.validate(valid_2d_float64())

    def test_valid_large_array_passes(self) -> None:
        self.v.validate(npy_bytes(np.random.rand(512, 512).astype(np.float32)))

    def test_1d_array_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="2D"):
            self.v.validate(npy_bytes(np.array([1.0, 2.0, 3.0], dtype=np.float32)))

    def test_3d_array_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="2D"):
            self.v.validate(npy_bytes(np.zeros((2, 3, 4), dtype=np.float32)))

    def test_int_dtype_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="float"):
            self.v.validate(npy_bytes(np.array([[1, 2], [3, 4]], dtype=np.int32)))

    def test_bool_dtype_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="float"):
            self.v.validate(npy_bytes(np.array([[True, False]], dtype=bool)))

    def test_invalid_bytes_raises(self) -> None:
        with pytest.raises(AssetValidationError):
            self.v.validate(b"not a numpy file at all")

    def test_empty_bytes_raises(self) -> None:
        with pytest.raises(AssetValidationError):
            self.v.validate(b"")

    def test_satisfies_asset_validator_protocol(self) -> None:
        assert isinstance(self.v, AssetValidator)


# ── VicariousCalGainsJsonValidator ───────────────────────────────────────────


class TestVicariousCalGainsJsonValidator:
    def setup_method(self) -> None:
        self.v = VicariousCalGainsJsonValidator()
        self.example = (
            EXAMPLES / "micro_vicarious_cal_gains_newsat46.json"
        ).read_bytes()

    def test_example_file_passes(self) -> None:
        self.v.validate(self.example)

    def test_all_integer_values_pass(self) -> None:
        payload = {
            band: {"scale_factor": 1, "bias_factor": 0}
            for band in ("blue", "green", "red", "nir")
        }
        self.v.validate(json.dumps(payload).encode())

    def test_missing_band_raises(self) -> None:
        payload = json.loads(self.example)
        del payload["nir"]
        with pytest.raises(AssetValidationError, match="missing bands"):
            self.v.validate(json.dumps(payload).encode())

    def test_extra_band_raises(self) -> None:
        payload = json.loads(self.example)
        payload["uv"] = {"scale_factor": 1.0, "bias_factor": 0.0}
        with pytest.raises(AssetValidationError, match="unexpected bands"):
            self.v.validate(json.dumps(payload).encode())

    def test_vicarious_cal_gains_band_not_a_dict_raises_validation_error(self) -> None:
        payload = {
            "blue": [0.989, 0],  # list instead of object
            "green": {"scale_factor": 0.956, "bias_factor": 0},
            "red": {"scale_factor": 0.976, "bias_factor": 0},
            "nir": {"scale_factor": 0.904, "bias_factor": 0},
        }
        with pytest.raises(AssetValidationError, match="'blue'.*must be an object"):
            self.v.validate(json.dumps(payload).encode())

    def test_scale_factor_as_string_raises(self) -> None:
        payload = json.loads(self.example)
        payload["blue"]["scale_factor"] = "not_a_number"
        with pytest.raises(AssetValidationError, match="numeric"):
            self.v.validate(json.dumps(payload).encode())

    def test_bias_factor_as_bool_raises(self) -> None:
        payload = json.loads(self.example)
        payload["red"]["bias_factor"] = True
        with pytest.raises(AssetValidationError, match="numeric"):
            self.v.validate(json.dumps(payload).encode())

    def test_missing_bias_factor_raises(self) -> None:
        payload = json.loads(self.example)
        del payload["green"]["bias_factor"]
        with pytest.raises(AssetValidationError, match="missing fields"):
            self.v.validate(json.dumps(payload).encode())

    def test_extra_field_in_band_raises(self) -> None:
        payload = json.loads(self.example)
        payload["blue"]["offset"] = 0.5
        with pytest.raises(AssetValidationError, match="unexpected fields"):
            self.v.validate(json.dumps(payload).encode())

    def test_non_dict_root_raises(self) -> None:
        with pytest.raises(AssetValidationError):
            self.v.validate(b"[1, 2, 3]")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="Invalid JSON"):
            self.v.validate(b"{not valid json}")

    def test_satisfies_asset_validator_protocol(self) -> None:
        assert isinstance(self.v, AssetValidator)


# ── BodyToPayloadJsonValidator ───────────────────────────────────────────────


class TestBodyToPayloadJsonValidator:
    def setup_method(self) -> None:
        self.v = BodyToPayloadJsonValidator()
        self.example = (EXAMPLES / "micro_body_to_payload_newsat50.json").read_bytes()

    def test_example_file_passes(self) -> None:
        self.v.validate(self.example)

    def test_integer_quaternion_elements_pass(self) -> None:
        self.v.validate(json.dumps({"quaternion": [0, 0, 0, 1]}).encode())

    def test_quaternion_with_3_elements_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="4 elements"):
            self.v.validate(json.dumps({"quaternion": [0.0, 0.0, 1.0]}).encode())

    def test_quaternion_with_5_elements_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="4 elements"):
            self.v.validate(
                json.dumps({"quaternion": [0.0, 0.0, 0.0, 1.0, 0.0]}).encode()
            )

    def test_quaternion_with_0_elements_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="4 elements"):
            self.v.validate(json.dumps({"quaternion": []}).encode())

    def test_non_numeric_element_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="numeric"):
            self.v.validate(json.dumps({"quaternion": [0.0, 0.0, 0.0, "x"]}).encode())

    def test_bool_element_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="numeric"):
            self.v.validate(json.dumps({"quaternion": [True, 0.0, 0.0, 1.0]}).encode())

    def test_missing_quaternion_key_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="quaternion"):
            self.v.validate(json.dumps({"attitude": [0.0, 0.0, 0.0, 1.0]}).encode())

    def test_quaternion_as_dict_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="list"):
            self.v.validate(json.dumps({"quaternion": {"w": 1.0}}).encode())

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(AssetValidationError, match="Invalid JSON"):
            self.v.validate(b"quaternion: [0,0,0,1]")

    def test_satisfies_asset_validator_protocol(self) -> None:
        assert isinstance(self.v, AssetValidator)


# ── AssetDefinitionRegistry ──────────────────────────────────────────────────


class TestAssetDefinitionRegistry:
    def setup_method(self) -> None:
        self.registry = AssetDefinitionRegistry()

    def test_all_four_asset_types_have_definitions(self) -> None:
        for asset_type in AssetType:
            defn = self.registry.get_definition(asset_type)
            assert defn.asset_type == asset_type

    def test_darkframe_definition_is_npy(self) -> None:
        defn = self.registry.get_definition(AssetType.DARKFRAME)
        assert defn.storage_format == StorageFormat.NPY

    def test_grayframe_definition_is_npy(self) -> None:
        defn = self.registry.get_definition(AssetType.GRAYFRAME)
        assert defn.storage_format == StorageFormat.NPY

    def test_vicarious_cal_gains_definition_is_json(self) -> None:
        defn = self.registry.get_definition(AssetType.VICARIOUS_CAL_GAINS)
        assert defn.storage_format == StorageFormat.JSON

    def test_body_to_payload_definition_is_json(self) -> None:
        defn = self.registry.get_definition(AssetType.BODY_TO_PAYLOAD)
        assert defn.storage_format == StorageFormat.JSON

    def test_all_definitions_have_schema_version(self) -> None:
        for asset_type in AssetType:
            defn = self.registry.get_definition(asset_type)
            assert defn.schema_version  # non-empty string

    def test_darkframe_validator_is_npy_validator(self) -> None:
        assert isinstance(
            self.registry.get_validator(AssetType.DARKFRAME),
            Npy2DFloatArrayValidator,
        )

    def test_grayframe_validator_is_npy_validator(self) -> None:
        assert isinstance(
            self.registry.get_validator(AssetType.GRAYFRAME),
            Npy2DFloatArrayValidator,
        )

    def test_vicarious_cal_gains_validator(self) -> None:
        assert isinstance(
            self.registry.get_validator(AssetType.VICARIOUS_CAL_GAINS),
            VicariousCalGainsJsonValidator,
        )

    def test_body_to_payload_validator(self) -> None:
        assert isinstance(
            self.registry.get_validator(AssetType.BODY_TO_PAYLOAD),
            BodyToPayloadJsonValidator,
        )

    def test_unknown_type_raises_for_get_definition(self) -> None:
        with pytest.raises(UnknownAssetTypeError):
            self.registry.get_definition(cast(AssetType, "totally_unknown"))

    def test_unknown_type_raises_for_get_validator(self) -> None:
        with pytest.raises(UnknownAssetTypeError):
            self.registry.get_validator(cast(AssetType, "totally_unknown"))


# ── AssetValidationService ───────────────────────────────────────────────────


class TestAssetValidationService:
    def setup_method(self) -> None:
        self.service = AssetValidationService(AssetDefinitionRegistry())

    def test_validate_darkframe_returns_validated_asset(self) -> None:
        result = self.service.validate(AssetType.DARKFRAME, valid_2d_float32())
        assert isinstance(result, ValidatedAsset)
        assert result.asset_type == AssetType.DARKFRAME

    def test_validate_grayframe_returns_validated_asset(self) -> None:
        result = self.service.validate(AssetType.GRAYFRAME, valid_2d_float64())
        assert isinstance(result, ValidatedAsset)
        assert result.asset_type == AssetType.GRAYFRAME

    def test_validate_vicarious_cal_gains_from_example(self) -> None:
        data = (EXAMPLES / "micro_vicarious_cal_gains_newsat46.json").read_bytes()
        result = self.service.validate(AssetType.VICARIOUS_CAL_GAINS, data)
        assert result.asset_type == AssetType.VICARIOUS_CAL_GAINS
        assert result.storage_format == StorageFormat.JSON

    def test_validate_body_to_payload_from_example(self) -> None:
        data = (EXAMPLES / "micro_body_to_payload_newsat50.json").read_bytes()
        result = self.service.validate(AssetType.BODY_TO_PAYLOAD, data)
        assert result.asset_type == AssetType.BODY_TO_PAYLOAD
        assert result.storage_format == StorageFormat.JSON

    def test_validated_asset_has_correct_schema_version_for_darkframe(self) -> None:
        result = self.service.validate(AssetType.DARKFRAME, valid_2d_float32())
        assert result.schema_version == "1.0"

    def test_validated_asset_darkframe_has_npy_storage_format(self) -> None:
        result = self.service.validate(AssetType.DARKFRAME, valid_2d_float32())
        assert result.storage_format == StorageFormat.NPY

    def test_invalid_darkframe_content_raises_asset_validation_error(self) -> None:
        with pytest.raises(AssetValidationError):
            self.service.validate(AssetType.DARKFRAME, b"not a npy file")

    def test_invalid_vicarious_cal_gains_raises_asset_validation_error(self) -> None:
        with pytest.raises(AssetValidationError):
            self.service.validate(
                AssetType.VICARIOUS_CAL_GAINS,
                json.dumps({"only_one_band": {}}).encode(),
            )

    def test_invalid_body_to_payload_raises_asset_validation_error(self) -> None:
        with pytest.raises(AssetValidationError):
            self.service.validate(
                AssetType.BODY_TO_PAYLOAD,
                json.dumps({"quaternion": [1.0, 2.0, 3.0]}).encode(),
            )

    def test_1d_npy_for_darkframe_raises_before_any_persistence(self) -> None:
        """Validation must fail early — no storage or metadata calls should happen."""
        bad_data = npy_bytes(np.array([1.0, 2.0, 3.0], dtype=np.float32))
        with pytest.raises(AssetValidationError, match="2D"):
            self.service.validate(AssetType.DARKFRAME, bad_data)
