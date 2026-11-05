"""Formato das respostas da API REST (Pydantic).

Os schemas definem exatamente o que sai da API: campos sensíveis (CPF inteiro,
RG, telefone, e-mail) não aparecem nas listagens; o CPF sai mascarado.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")
Kind = Literal["resident", "collaborator", "visitor"]


class Page(BaseModel, Generic[T]):
    total: int
    page: int
    size: int
    items: list[T]


class CondominiumOut(BaseModel):
    id: int
    name: str
    units: int
    residents: int
    collaborators: int
    visitors: int
    synced_at: datetime | None


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    block: str | None
    unity: str | None
    full_unity: str | None
    is_condominium: bool


class PersonOut(BaseModel):
    id: int
    gear_id: int
    kind: Kind
    condominium_id: int
    unit_id: int | None
    unit: str | None
    full_name: str | None
    cpf_masked: str | None
    permission: bool | None
    blocked: bool | None
    start_date: date | None
    expiration_date: date | None
    expired: bool | None


class DuplicateCpfOut(BaseModel):
    cpf_masked: str
    registrations: int
    condominiums: list[int]
    names: list[str]


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    condominiums: int
    units: int
    persons: int
    removed: int
    api_calls: int
    errors: list | None
