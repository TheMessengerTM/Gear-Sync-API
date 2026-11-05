FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências primeiro: o Docker reaproveita esta camada enquanto o pyproject não mudar
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home app
USER app

EXPOSE 8000
# Aplica as migrations e sobe a API
CMD ["sh", "-c", "alembic upgrade head && uvicorn gear_sync.api:app --host 0.0.0.0 --port 8000"]
