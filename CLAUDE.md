# SCAR project instructions

This repository implements the Satellite Calibration Asset Registry described in `DESIGN.md`.

When working on implementation, tests, refactors, or design consistency, use the `scar-implementation` skill.

Always preserve these rules:

- `admin_api` and `pipeline_api` must not import each other.
- Temporal windows are half-open: `[valid_from, valid_to)`.
- No overlapping versions are allowed for the same `(satellite_id, asset_type)`.
- Historical asset versions remain valid under their original `schema_version`.
- Metadata is the source of truth; cache is an optimization.