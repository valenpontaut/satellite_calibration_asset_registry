from __future__ import annotations

import io
import json
from typing import Protocol, runtime_checkable

import numpy as np


class AssetValidationError(Exception):
    pass


def _is_numeric(val: object) -> bool:
    # Exclude bool: JSON true/false map to Python bool, which is a subclass of int.
    return isinstance(val, (int, float)) and not isinstance(val, bool)


@runtime_checkable
class AssetValidator(Protocol):
    def validate(self, data: bytes) -> None: ...


class Npy2DFloatArrayValidator:
    def validate(self, data: bytes) -> None:
        try:
            arr = np.load(io.BytesIO(data))
        except Exception as exc:
            raise AssetValidationError(f"Cannot parse .npy file: {exc}") from exc
        if arr.ndim != 2:
            raise AssetValidationError(
                f"Expected 2D array, got {arr.ndim}D (shape {arr.shape})"
            )
        if not np.issubdtype(arr.dtype, np.floating):
            raise AssetValidationError(f"Expected float dtype, got {arr.dtype!r}")


_VICARIOUS_BANDS = frozenset({"blue", "green", "red", "nir"})
_BAND_FIELDS = frozenset({"scale_factor", "bias_factor"})


class VicariousCalGainsJsonValidator:
    def validate(self, data: bytes) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AssetValidationError(f"Invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise AssetValidationError(
                f"Expected a JSON object at root, got {type(payload).__name__!r}"
            )
        bands = set(payload.keys())
        if bands != _VICARIOUS_BANDS:
            missing = sorted(_VICARIOUS_BANDS - bands)
            extra = sorted(bands - _VICARIOUS_BANDS)
            parts: list[str] = []
            if missing:
                parts.append(f"missing bands: {missing}")
            if extra:
                parts.append(f"unexpected bands: {extra}")
            raise AssetValidationError("; ".join(parts))
        for band, fields in payload.items():
            if not isinstance(fields, dict):
                raise AssetValidationError(
                    f"Band {band!r} must be an object, got {type(fields).__name__!r}"
                )
            field_keys = set(fields.keys())
            if field_keys != _BAND_FIELDS:
                missing_f = sorted(_BAND_FIELDS - field_keys)
                extra_f = sorted(field_keys - _BAND_FIELDS)
                parts = []
                if missing_f:
                    parts.append(f"missing fields in band {band!r}: {missing_f}")
                if extra_f:
                    parts.append(f"unexpected fields in band {band!r}: {extra_f}")
                raise AssetValidationError("; ".join(parts))
            for field in ("scale_factor", "bias_factor"):
                val = fields[field]
                if not _is_numeric(val):
                    raise AssetValidationError(
                        f"Band {band!r}.{field!r} must be numeric, "
                        f"got {type(val).__name__!r}"
                    )


class BodyToPayloadJsonValidator:
    def validate(self, data: bytes) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AssetValidationError(f"Invalid JSON: {exc}") from exc
        if not isinstance(payload, dict) or "quaternion" not in payload:
            raise AssetValidationError("Expected a JSON object with a 'quaternion' key")
        q = payload["quaternion"]
        if not isinstance(q, list):
            raise AssetValidationError(
                f"'quaternion' must be a list, got {type(q).__name__!r}"
            )
        if len(q) != 4:
            raise AssetValidationError(
                f"'quaternion' must have exactly 4 elements, got {len(q)}"
            )
        for i, val in enumerate(q):
            if not _is_numeric(val):
                raise AssetValidationError(
                    f"'quaternion[{i}]' must be numeric, got {type(val).__name__!r}"
                )
