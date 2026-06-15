FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY shared/ ./shared/
COPY admin_api/ ./admin_api/
COPY pipeline_api/ ./pipeline_api/

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "admin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
