# `.claude/skills/scar-implementation/SKILL.md`

name: scar-implementation
description: Implement the Satellite Calibration Asset Registry (SCAR) backend. Use when coding, refactoring, testing, or reviewing SCAR domain logic, APIs, repositories, validation, temporal versioning, caching, Docker setup, or README/DESIGN consistency.

# SCAR Implementation Skill

You are helping implement **SCAR — Satellite Calibration Asset Registry**, a Python + Docker Compose technical exercise.

The implementation must match the architecture documented in `DESIGN.md`.

## Core product goal

SCAR is the single source of truth for calibration assets across a satellite fleet.

Supported assets:

- `darkframe`: 2D float array
- `grayframe`: 2D float array
- `vicarious_cal_gains`: JSON with per-band scale/bias factors
- `body_to_payload`: JSON with payload attitude quaternion

Each asset belongs to:

```text
(satellite_id, asset_type)
```

and has a temporal validity window:

```text
[valid_from, valid_to)
```

`valid_to = null` means open-ended validity.

## Non-negotiable domain invariant

For each `(satellite_id, asset_type)`, no two versions may overlap in time.

At any timestamp there may be:

* exactly one valid version, or
* zero valid versions if the asset has not been characterized yet.

Gaps ARE allowed (a satellite may have no characterized asset for a period). Only overlaps are forbidden. Never allow ambiguous point-in-time resolution.

## Architecture boundaries

Use a monorepo:

```text
scar/
├── shared/
│   ├── domain/
│   ├── validation/
│   ├── repositories/
│   └── config/
├── admin_api/
│   ├── routers/
│   ├── services/
│   └── main.py
├── pipeline_api/
│   ├── routers/
│   ├── services/
│   └── main.py
├── migrations/
└── tests/
```

Dependency rule:

```text
admin_api -> shared
pipeline_api -> shared
shared.repositories -> shared.domain
shared.validation -> shared.domain
```

`admin_api` and `pipeline_api` must never import each other.

## API responsibilities

### admin_api

Owns write workflows:

1. Validate uploaded asset content.
2. Store blob/asset content (see "Asset content storage" below).
3. Resolve temporal overlaps (possibly multiple affected rows — see "Overlap resolution" below).
4. Insert/update/delete metadata rows inside one transaction.
5. Insert audit log entry/entries.
6. Increment cache `dataset_version`.

Admin writes are infrequent. Prefer correctness and clarity over micro-optimizations.

### pipeline_api

Owns high-throughput read workflows:

1. Point-in-time resolution:

   * input: `satellite_id`, `asset_type`, `timestamp`
   * output: exact asset version valid at that timestamp, or explicit not-found response.
2. Bulk resolution:

   * input: `satellite_id`, `timestamp`
   * output: all active asset versions for that satellite at that moment (one entry per `asset_type`, with explicit "not found" markers for types with no active version).

Pipeline API should not stream large blobs. It should return metadata plus presigned object storage URLs (for `darkframe`/`grayframe`; see "Asset content storage" for JSON-type assets).

## Domain model

Implement these concepts in `shared.domain`:

* `AssetVersion`
* `AuditLogEntry`
* `AssetType`
* `StorageFormat`
* `AuditOperation`
* `OverlapType`

`AssetVersion` should include:

```text
id
satellite_id
asset_type
schema_version
valid_from
valid_to
blob_ref
```

Use half-open intervals:

```text
valid_from <= timestamp < valid_to
```

For open-ended versions:

```text
valid_to is null
```

means valid forever after `valid_from`.

### `OverlapType` vs `AuditOperation` — these are distinct enums

`OverlapType` (`EXTEND`, `SPLIT`, `FULL_COVERAGE`) classifies how the *new* version's window relates to an *existing* row during overlap resolution. It is an internal decision label used by `resolve_overlaps`.

`AuditOperation` (`CREATE`, `EXTEND`, `SPLIT`, `FULL_COVERAGE_DELETE`, `RETIRE`) describes what happened to a *specific row*, for the audit log. A single admin write can produce multiple `AuditLogEntry` rows with different operations (see "Overlap resolution" below). Do not try to unify these two enums — they answer different questions ("how does the new window relate to this old row" vs "what was done to this row, for the audit trail").

## Validation and schema evolution

Before persisting any asset content, validate it according to the current `AssetDefinition`.

Use a validation layer:

```text
shared.validation
├── AssetDefinition
├── AssetDefinitionRegistry
├── AssetValidator
├── Npy2DFloatArrayValidator
├── VicariousCalGainsJsonValidator
└── BodyToPayloadJsonValidator
```

Rules:

* Invalid uploads must fail before any persistence (storage or metadata).
* `darkframe` and `grayframe` must be 2D arrays of floats.
* `vicarious_cal_gains` must match the expected JSON band structure (per-band `scale_factor`/`bias_factor` for `blue`, `green`, `red`, `nir` — see `examples/micro_vicarious_cal_gains_newsat46.json`).
* `body_to_payload` must contain a valid quaternion structure: a `quaternion` field with exactly 4 floats (see `examples/micro_body_to_payload_newsat50.json`).
* Each inserted `AssetVersion` stores the `schema_version` used at upload time.
* Historical versions remain valid under their original schema version.
* Do not reinterpret or invalidate old versions when a new schema is introduced.

## Asset content storage

All four asset types use `blob_ref` and `ObjectStorageRepository` uniformly — including the small JSON assets (`vicarious_cal_gains`, `body_to_payload`).

Rationale: this avoids two different code paths in the write/read flows (one for "embedded metadata" and one for "blob_ref + presigned URL"), keeps `AssetVersion` schema uniform across all `AssetType` values, and keeps `metadata_store` rows small regardless of asset type. The size difference (a few KB of JSON vs. MBs of `.npy` arrays) does not justify branching the storage strategy.

Consequence for `pipeline_api`: point-in-time and bulk resolution responses return metadata + a presigned URL for **all** asset types, including JSON ones. Callers fetch the JSON content from object storage the same way they'd fetch a `.npy` array. Do not special-case JSON assets to embed their content directly in the API response.

## Overlap resolution (`AssetAdminService.resolve_overlaps`)

Given a new version window `[new_from, new_to)` for `(satellite_id, asset_type)`:

1. Find ALL existing versions for the same `(satellite_id, asset_type)` whose windows overlap `[new_from, new_to)`. There can be more than one.
2. Classify and handle EACH overlapping row independently:

   * `EXTEND`: the existing row's window starts before `new_from` and the new window absorbs its tail (existing `valid_to` is `null` or `> new_from`, and existing `valid_from < new_from`) → truncate the existing row's `valid_to = new_from`. Audit as `EXTEND`.
   * `SPLIT`: the new window falls strictly inside the existing row's window (`existing.valid_from < new_from` and (`existing.valid_to is null` or `existing.valid_to > new_to`)) → split the existing row into two rows: one `[existing.valid_from, new_from)`, one `[new_to, existing.valid_to)`, both referencing the same immutable `blob_ref` and `schema_version` as the original. Audit as `SPLIT` (the original row is logically replaced by two new rows — audit the split, referencing the original row's id).
   * `FULL_COVERAGE`: the new window fully contains the existing row's window (`new_from <= existing.valid_from` and (`new_to is null` or (`existing.valid_to is not null` and `new_to >= existing.valid_to`))) → delete the existing row entirely. Audit as `FULL_COVERAGE_DELETE`.
   * A row whose window starts at or after `new_to` (when `new_to` is not null) but still overlaps doesn't fit the cases above in this design — this would mean the new window has a `valid_to` and lands inside or overlapping the start of an existing row. Treat this symmetrically to `SPLIT`/`EXTEND` from the other side: if `new_from <= existing.valid_from < new_to`, truncate the existing row's `valid_from = new_to` instead of `valid_to` (call this the mirrored `EXTEND` case — same `AuditOperation.EXTEND`, but the existing row's start is moved forward instead of its end being moved back).
3. A single write may produce a mix of the above across multiple rows (e.g., one `EXTEND` on one side and one `FULL_COVERAGE_DELETE` further out). Each affected row gets its own `AuditLogEntry`.
4. Insert the new version row, with `AuditOperation.CREATE`.
5. All metadata mutations (updates, splits, deletes, insert) and all audit log entries happen in ONE atomic transaction.
6. On commit, increment `dataset_version` for `(satellite_id, asset_type)` exactly once, regardless of how many rows were affected.

### Example: multi-overlap write

Existing rows for `(newsat80, grayframe)`:

* Row A: `[2027-09-18, 2028-06-01)`
* Row B: `[2028-06-01, null)` (open-ended)

New upload: `[2028-02-07, 2028-09-01)`

Resolution:

* Row A overlaps: new window starts inside A and ends after A's end → `SPLIT` is not right here since the new window extends past A's `valid_to`. This is the mirrored case: A's `valid_to` is truncated to `2028-02-07` (EXTEND-style truncation from A's side).
* Row B overlaps: new window's end (`2028-09-01`) falls inside B's open-ended window, and starts before B starts → Row B's `valid_from` is truncated to `2028-09-01` (mirrored `EXTEND`).
* New row inserted: `[2028-02-07, 2028-09-01)`.
* Result: A is `[2027-09-18, 2028-02-07)`, new row is `[2028-02-07, 2028-09-01)`, B is `[2028-09-01, null)`. No gaps, no overlaps.
* Three audit entries: `EXTEND` (Row A), `EXTEND` (Row B), `CREATE` (new row).

## Cache strategy

Cache keys are namespaced by `dataset_version` for `(satellite_id, asset_type)`.

### Key format

```text
v{dataset_version}:{satellite_id}:{asset_type}:pit:{timestamp_iso}
v{dataset_version}:{satellite_id}:bulk:{timestamp_iso}
```

* `timestamp_iso`: the queried timestamp normalized to UTC, ISO 8601, second precision (truncate finer precision — calibration validity windows don't change at sub-second granularity, and truncation improves cache hit rates).
* For bulk queries, `dataset_version` in the key is a composite/concatenation of the `dataset_version` values for all `asset_type`s of that satellite (e.g., join sorted `f"{asset_type}={version}"` pairs with `,`), since any one of them changing must invalidate the bulk cache entry. `CacheRepository.get_dataset_version` for bulk queries should accept a satellite_id and asset_type list and return this composite.
* `build_cache_key` (in `AssetResolutionService`) is the single place this format is constructed — both `resolve_point_in_time` and `resolve_bulk` must call it, never inline string formatting.

### TTL strategy

* `valid_to` set (closed/historical window) → long TTL (e.g., 24h — content can never change for a closed historical window).
* `valid_to = NULL` (open/active window) → short TTL (e.g., 60s — the active version could be superseded soon).
* No-asset-found responses → short TTL, same as open-ended (a gap could be filled by a future upload).

Any write bumps `dataset_version`, making previously cached keys unreachable. Never rely on cache for correctness — metadata store is the source of truth.

## Audit log

`AuditLogEntry.details` (a `Map`/JSON field) must contain, at minimum:

```json
{
  "asset_type": "...",
  "valid_from": "...",
  "valid_to": "..." ,
  "blob_ref": "...",
  "schema_version": "..."
}
```

i.e., a snapshot of the affected `AssetVersion`'s temporal/identity fields *after* the operation (for `FULL_COVERAGE_DELETE`, snapshot the row *before* deletion — its last known state). This is sufficient to reconstruct "what the row looked like" without needing a full diff engine, and supports the bonus requirement of traceability ("who changed what and when").

`operator_id` is a free-text identifier (username or API key) provided with the admin request — no auth/authz validation in the MVP.

## No-asset-found handling

### Point-in-time response contract

Return HTTP 200 with a structured body indicating presence/absence explicitly — do not use 404 for "no version valid at this timestamp" (404 is reserved for unknown `satellite_id`/`asset_type`/malformed requests).

```json
{
  "found": false,
  "satellite_id": "...",
  "asset_type": "...",
  "timestamp": "..."
}
```

or, when found:

```json
{
  "found": true,
  "asset_version": { "...": "..." },
  "presigned_url": "..."
}
```

### Bulk response contract

One entry per known `AssetType`, each following the point-in-time shape above (`found: true/false`). Never omit an asset type from the bulk response just because it has no active version — omission is ambiguous (caller can't tell "no version" from "forgot to check").

## Repositories

Use repository abstractions in `shared.repositories`:

```text
AdminMetadataRepository
PipelineMetadataRepository
CacheRepository
ObjectStorageRepository
```

Expected responsibilities:

* `AdminMetadataRepository`

  * `find_overlapping`
  * `insert_version`
  * `update_version`
  * `delete_version`
  * `insert_audit_log`
* `PipelineMetadataRepository`

  * `find_point_in_time`
  * `find_bulk`
* `CacheRepository`

  * `get`
  * `set`
  * `get_dataset_version`
  * `incr_dataset_version`
* `ObjectStorageRepository`

  * `put_object`
  * `generate_presigned_url`

## Migrations

Use Alembic for `metadata_store` schema migrations, living under `migrations/`. Every change to `AssetVersion`/`AuditLogEntry` table shapes must come with a corresponding Alembic revision. `pytest` setup for integration tests should run migrations against a test database (not `create_all`), so migration drift is caught early.

## Testing expectations

Prioritize tests for temporal correctness.

Must cover:

* first asset version insertion (no existing rows)
* extending an open-ended version (single-row EXTEND)
* mirrored EXTEND (new version with explicit `valid_to`, truncating an existing row's `valid_from`)
* inserting a version that splits an existing interval (SPLIT)
* full coverage replacement (FULL_COVERAGE_DELETE)
* multi-row overlap in a single write (e.g., the multi-overlap example above) — assert correct classification per row AND correct audit entry count/content
* point-in-time lookup (found and not-found)
* bulk lookup (mixed found/not-found per asset type)
* cache key format for point-in-time and bulk (including dataset_version composite for bulk)
* TTL selection (open vs closed vs not-found)
* invalid upload rejected before any persistence (storage or metadata)
* schema version stored on upload
* cache version bump on successful write (exactly once per write, even with multiple affected rows)
* audit log entry content (`details` snapshot) for each `AuditOperation`

Use clear test names that describe the domain behavior.

Also keep CI green:

- `pytest` must pass
- Coverage must be generated with `pytest-cov`
- Prefer adding tests for every domain rule before or alongside implementation

## Coding style

Prefer:

* small services with explicit responsibilities
* typed Python
* Pydantic models for request/response/domain validation where useful
* explicit timezone-aware datetimes (UTC)
* dependency injection for repositories/services
* readable transaction boundaries
* simple, boring code over clever abstractions

Avoid:

* hidden cross-service imports between `admin_api` and `pipeline_api`
* temporal logic duplicated in routers
* cache invalidation by deleting arbitrary keys
* mutating blobs after upload
* silently accepting unknown asset types
* returning ambiguous query results
* branching storage strategy by asset type (see "Asset content storage")

## Before coding

When starting a task:

1. Read `DESIGN.md`.
2. Identify whether the change belongs to:

   * `admin_api`
   * `pipeline_api`
   * `shared.domain`
   * `shared.validation`
   * `shared.repositories`
   * `shared.config`
   * `migrations`
3. Keep the dependency direction consistent.
4. Add or update tests for the relevant invariant.

## Repository documentation

The repository must include:

- `README.md`: usage instructions, Docker commands, testing, coverage, and examples.
- `DESIGN.md`: architecture and design decisions.
- `examples/`: sample calibration assets used for manual testing and documentation.
- `assets/`: architecture diagrams referenced from `DESIGN.md`.

When adding commands or endpoints, keep `README.md` updated.