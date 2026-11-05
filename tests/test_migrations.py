"""Garante que as migrations do Alembic estão em dia com os models.

Se alguém mudar models.py e esquecer de gerar a migration, este teste falha.
"""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from gear_sync.db import Base


def test_migrations_batem_com_os_models(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
