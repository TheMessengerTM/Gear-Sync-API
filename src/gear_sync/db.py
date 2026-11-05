"""Conexão com o banco.

A URL vem de DATABASE_URL. Em produção/Docker é PostgreSQL
(postgresql+psycopg://usuario:senha@host:5432/banco); sem a variável,
usa um SQLite local (gear.db) para facilitar testes rápidos.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_URL = "sqlite:///gear.db"


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url == "sqlite://" or url.endswith(":memory:"):
        # SQLite em memória: uma única conexão compartilhada, senão cada sessão veria um banco vazio
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no final."""
    with SessionLocal() as session:
        yield session
