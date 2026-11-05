"""Tabelas do banco (SQLAlchemy 2.0, estilo tipado).

condominiums 1──N units 1──N persons
sync_runs: histórico de cada sincronização.

Campos de senha de acesso que a API GEAR devolve (password_access, ...)
NÃO são guardados: não há motivo para o banco ter isso.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

PERSON_KINDS = ("resident", "collaborator", "visitor")


class Condominium(Base):
    __tablename__ = "condominiums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # id do GEAR
    name: Mapped[str] = mapped_column(String(200))
    id_integration: Mapped[str | None] = mapped_column(String(50))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    units: Mapped[list[Unit]] = relationship(back_populates="condominium", cascade="all, delete-orphan")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # id do GEAR
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id", ondelete="CASCADE"), index=True)
    block: Mapped[str | None] = mapped_column(String(100))
    unity: Mapped[str | None] = mapped_column(String(100))
    full_unity: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # True = unidade que representa o próprio condomínio (onde ficam os funcionários do prédio)
    is_condominium: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    condominium: Mapped[Condominium] = relationship(back_populates="units")


class Person(Base):
    __tablename__ = "persons"
    # O mesmo id do GEAR pode se repetir entre tipos diferentes → a chave natural é (kind, gear_id)
    __table_args__ = (UniqueConstraint("kind", "gear_id", name="uq_persons_kind_gear_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # resident | collaborator | visitor
    gear_id: Mapped[int] = mapped_column(Integer)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id", ondelete="CASCADE"), index=True)
    # sem FK: a API às vezes aponta para uma unidade que não existe mais
    unit_id: Mapped[int | None] = mapped_column(Integer, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), index=True)
    cpf: Mapped[str | None] = mapped_column(String(11), index=True)  # só dígitos
    rg: Mapped[str | None] = mapped_column(String(30))
    birthday: Mapped[date | None] = mapped_column(Date)
    cell_number: Mapped[str | None] = mapped_column(String(30))
    cell_number_2: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    permission: Mapped[bool | None] = mapped_column(Boolean)
    blocked: Mapped[bool | None] = mapped_column(Boolean)
    start_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date, index=True)
    start_hour: Mapped[str | None] = mapped_column(String(8))
    end_hour: Mapped[str | None] = mapped_column(String(8))
    # {"monday": {"allowed": true, "start": "08:00", "end": "18:00"}, ...}
    schedule: Mapped[dict | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    id_integration: Mapped[str | None] = mapped_column(String(50))
    photo_url: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | partial | error
    condominiums: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(Integer, default=0)
    persons: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSON)
