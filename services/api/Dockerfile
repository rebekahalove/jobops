FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/services/api

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY jobops_api ./jobops_api

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN addgroup --system jobops \
    && adduser --system --ingroup jobops --home /app jobops \
    && chown -R jobops:jobops /app

USER jobops

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "jobops_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
