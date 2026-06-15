# SCAR — Satellite Calibration Asset Registry

SCAR is a Python + Docker Compose implementation of a Satellite Calibration Asset Registry.

## Run locally
Start the full stack:

```bash
docker compose up --build
```

## Run tests

```
pytest
```

## Run tests with coverage

```
pytest --cov=admin_api --cov=pipeline_api --cov=shared --cov-report=term-missing
```

## Development checks

Run formatting, linting, typing, and tests locally:

```
ruff format .
ruff check .
mypy .
pytest
```

## Continuous Integration

The repository includes a GitHub Actions CI pipeline that automatically runs on pushes and pull requests.

The pipeline validates:

- formatting (ruff format --check)
- linting (ruff check)
- static typing (mypy)
- security analysis (bandit)
- tests (pytest)
- coverage reporting (pytest-cov)

## Example assets

Sample calibration files are available under examples/:

- micro_darkframe_newsat53.npy
- micro_grayframe_newsat53.npy
- micro_vicarious_cal_gains_newsat46.json
- micro_body_to_payload_newsat50.json
These examples are useful for manual testing and API validation.


## Architecture

Architecture decisions and design rationale are documented in `DESIGN.md`

Architecture diagrams and UML assets are stored under `assets/`

Main diagrams included:

- Use case diagram
- Deployment diagram
- Package diagram
- Class diagram

## Main technologies
- Python 3.11
- FastAPI
- Docker Compose
- PostgreSQL
- Redis
- S3-compatible object storage
- Pytest
- Ruff
- Mypy
- GitHub Actions