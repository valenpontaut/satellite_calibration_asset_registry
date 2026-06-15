FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY shared/ ./shared/
COPY admin_api/ ./admin_api/
COPY pipeline_api/ ./pipeline_api/
COPY migrations/ ./migrations/
COPY alembic.ini .

RUN pip install --no-cache-dir -e .

EXPOSE 8001

CMD ["sh", "-c", "alembic upgrade head && uvicorn pipeline_api.main:app --host 0.0.0.0 --port 8001"]
