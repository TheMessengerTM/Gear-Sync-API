"""Fixtures compartilhadas pelos testes.

Banco: TEST_DATABASE_URL se definida (no CI é um PostgreSQL de verdade);
senão SQLite em memória. As tabelas são criadas rodando as MIGRATIONS do
Alembic — assim os testes também garantem que as migrations funcionam.
"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gear_sync.client import GearClient
from gear_sync.db import Base, make_engine
from gear_sync.mock_gear import build_dataset, create_app

ROOT = Path(__file__).resolve().parents[1]
TEST_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


def run_migrations(connection, action="upgrade", target="head"):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    getattr(command, action)(cfg, target)


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_URL)
    with eng.begin() as conn:
        run_migrations(conn, "downgrade", "base")  # começa do zero mesmo num Postgres reaproveitado
        run_migrations(conn, "upgrade", "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s
    # limpa todas as tabelas depois de cada teste (ordem reversa por causa das FKs)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def dataset():
    return build_dataset(seed=7, n_condos=3)


@pytest.fixture
def mock_app(dataset):
    """Servidor GEAR falso (FastAPI) rodando em memória, sem rede."""
    return create_app(dataset)


@pytest.fixture
def gear(mock_app):
    """GearClient de verdade, falando com o servidor falso."""
    http = TestClient(mock_app, base_url="http://gear.test/api")
    with GearClient("token-de-teste", min_interval=0, http_client=http) as c:
        yield c
