# SCAR — Satellite Calibration Asset Registry

SCAR is the single source of truth for calibration assets (`darkframe`, `grayframe`,
`vicarious_cal_gains`, `body_to_payload`) across a satellite fleet. Each asset version
has a half-open temporal validity window `[valid_from, valid_to)`. See `DESIGN.md` for
full architecture documentation.

---

## Usage

### 1. Start the stack

```bash
docker compose up --build
```

This starts:
- `admin-api` on port **8000**
- `pipeline-api` on port **8001**
- PostgreSQL (`metadata_store`) on port **5432**
- Redis (`cache`) on port **6379**
- MinIO (`object_storage`) on ports **9000** (S3 API) and **9001** (console)

### 2. Database migrations

Migrations run automatically at container startup — both `admin-api` and `pipeline-api`
execute `alembic upgrade head` before launching Uvicorn. Alembic is idempotent: running
on an already-migrated database is a no-op. No manual step is needed.

### 3. API endpoints

#### Admin API (port 8000)

**Upload a new asset version**

```bash
# darkframe (.npy array)
curl -X POST http://localhost:8000/assets \
  -F satellite_id=newsat53 \
  -F asset_type=darkframe \
  -F valid_from=2025-01-01T00:00:00Z \
  -F operator_id=ops_team \
  -F file=@examples/micro_darkframe_newsat53.npy

# grayframe (.npy array)
curl -X POST http://localhost:8000/assets \
  -F satellite_id=newsat53 \
  -F asset_type=grayframe \
  -F valid_from=2025-01-01T00:00:00Z \
  -F operator_id=ops_team \
  -F file=@examples/micro_grayframe_newsat53.npy

# vicarious_cal_gains (JSON)
curl -X POST http://localhost:8000/assets \
  -F satellite_id=newsat46 \
  -F asset_type=vicarious_cal_gains \
  -F valid_from=2025-01-01T00:00:00Z \
  -F operator_id=ops_team \
  -F file=@examples/micro_vicarious_cal_gains_newsat46.json

# body_to_payload (JSON), with explicit valid_to
curl -X POST http://localhost:8000/assets \
  -F satellite_id=newsat50 \
  -F asset_type=body_to_payload \
  -F valid_from=2025-01-01T00:00:00Z \
  -F "valid_to=2025-12-31T23:59:59Z" \
  -F operator_id=ops_team \
  -F file=@examples/micro_body_to_payload_newsat50.json
```

**Retire an existing version** (close an open-ended window)

```bash
curl -X DELETE "http://localhost:8000/assets/<version-id>/retire" \
  -H "Content-Type: application/json" \
  -d '{"retired_at": "2025-06-01T00:00:00Z", "operator_id": "ops_team"}'
```

Replace `<version-id>` with the UUID returned by the upload response.

**Health check**

```bash
curl http://localhost:8000/health
```

#### Pipeline API (port 8001)

**Point-in-time resolution**

```bash
curl "http://localhost:8001/resolve?satellite_id=newsat53&asset_type=darkframe&timestamp=2025-03-01T00:00:00Z"
```

Returns `{"found": true, "asset_version": {...}, "presigned_url": "..."}` or
`{"found": false, "satellite_id": ..., "asset_type": ..., "timestamp": ...}`.

**Bulk resolution** (all asset types for a satellite at a given timestamp)

```bash
curl "http://localhost:8001/resolve/bulk?satellite_id=newsat53&timestamp=2025-03-01T00:00:00Z"
```

Returns one entry per `AssetType`, each with the same shape as the point-in-time response.
Asset types with no active version appear as `found: false` — they are never omitted.

**Health check**

```bash
curl http://localhost:8001/health
```

---

## Run tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=admin_api --cov=pipeline_api --cov=shared --cov-report=term-missing
```

## Development checks

```bash
ruff format .
ruff check .
mypy .
pytest
```

## Continuous Integration

The repository includes a GitHub Actions CI pipeline that runs on every push and pull
request. It validates formatting (`ruff format --check`), linting (`ruff check`),
static typing (`mypy`), security analysis (`bandit`), tests (`pytest`), and coverage
(`pytest-cov`).

---

## Key design decisions

Full rationale is in `DESIGN.md`. Summary:

**Temporal versioning — half-open intervals, `resolve_overlaps`**
Each `AssetVersion` has a `[valid_from, valid_to)` window. No two versions for the same
`(satellite_id, asset_type)` may overlap. On every upload, `resolve_overlaps` classifies
each conflicting existing row as EXTEND, SPLIT, FULL_COVERAGE, or mirrored EXTEND, and
mutates them atomically alongside the new version insert. Gaps are allowed; ambiguity is
not.

**Storage — uniform `blob_ref` for all asset types**
`darkframe`, `grayframe`, `vicarious_cal_gains`, and `body_to_payload` all go through
`ObjectStorageRepository.put_object` and are referenced by `blob_ref`. The pipeline
returns presigned URLs for all types — no separate code path for small JSON assets. This
keeps `AssetVersion` schema uniform and the read/write paths branchless.

**Cache — `dataset_version` namespacing, differentiated TTL**
Cache keys include a per-`(satellite_id, asset_type)` `dataset_version` counter that is
incremented on every write. Previously cached answers become unreachable immediately
without requiring explicit invalidation. TTL: 86400 s for closed windows (content is
immutable), 60 s for open-ended or not-found responses (a new upload could supersede
them at any time). Bulk cache TTL is the minimum across all per-type TTLs.

**Audit log — no FK to `asset_versions`**
`audit_log.asset_version_id` is not a foreign key. FULL_COVERAGE_DELETE removes rows
from `asset_versions`; without this decision, the audit trail would need to be deleted
too, undermining traceability. Every affected row gets its own `AuditLogEntry` with a
before-mutation snapshot of its temporal fields and `blob_ref`.

---

## Resolved open assumptions

These were listed as open in `DESIGN.md` and have been resolved in the implementation:

- **Storage of small JSON assets** (`vicarious_cal_gains`, `body_to_payload`) → same
  object storage path as binary assets. Uniform `blob_ref` model, no special-casing.
- **Not-found response** → HTTP 200 with `{"found": false, ...}`, not HTTP 404.
  HTTP 404 is reserved for malformed requests (unknown `asset_type` enum value, etc.).
- **`operator_id`** → free-text string passed with each admin request. No
  authentication or authorization in the MVP.
- **HTTP 409 for unresolvable overlaps** → not implemented. `resolve_overlaps`
  always resolves: every overlap falls into EXTEND, SPLIT, FULL_COVERAGE, or mirrored
  EXTEND. A 409 would only apply if a future constraint (e.g., a lock or explicit
  "no-overwrite" flag per version) made some overlaps irresolvable. Tracked as a
  future extension.

---

## AI tooling

This project was developed using **Claude Code** (Anthropic) with structured, persistent
context via `CLAUDE.md` and `.claude/skills/scar-implementation/SKILL.md`. The skill
file encodes domain invariants, overlap-resolution logic, cache key formats, and audit
requirements in a form that survives across sessions — reducing drift between design
intent and implementation without manual re-briefing.

---

## Example assets

Sample calibration files for manual testing are under `examples/`:

| File | Type |
|---|---|
| `micro_darkframe_newsat53.npy` | 2D float array (darkframe) |
| `micro_grayframe_newsat53.npy` | 2D float array (grayframe) |
| `micro_vicarious_cal_gains_newsat46.json` | Per-band scale/bias factors |
| `micro_body_to_payload_newsat50.json` | Payload attitude quaternion |

---

## Architecture

See `DESIGN.md` for the full 4+1 view (use case, physical, process, development,
logical). Diagrams are under `assets/`.

## Main technologies

- Python 3.11 / FastAPI / Uvicorn
- PostgreSQL 16 (metadata store, Alembic migrations)
- Redis 7 (versioned cache)
- MinIO (S3-compatible object storage)
- Docker Compose
- Pytest / pytest-cov / Ruff / Mypy / GitHub Actions
