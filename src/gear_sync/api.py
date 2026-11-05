"""API REST (FastAPI) sobre os dados sincronizados.

    uvicorn gear_sync.api:app --reload      → documentação em http://localhost:8000/docs
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import __doc__ as pkg_doc
from .db import get_session
from .models import Condominium, Person, SyncRun, Unit
from .schemas import (
    CondominiumOut,
    DuplicateCpfOut,
    Kind,
    Page,
    PersonOut,
    SyncRunOut,
    UnitOut,
)
from .transform import mask_cpf

app = FastAPI(
    title="Gear-Sync API",
    description=pkg_doc,
    version="0.1.0",
)

SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/health", tags=["infra"])
def health(session: SessionDep):
    session.execute(select(1))
    return {"status": "ok"}


# ------------------------------------------------------------ condomínios
def _condo_query():
    count = lambda kind: func.count(case((Person.kind == kind, 1)))  # noqa: E731
    units = (select(func.count(Unit.id)).where(Unit.condominium_id == Condominium.id)
             .correlate(Condominium).scalar_subquery())
    return (
        select(Condominium.id, Condominium.name, Condominium.synced_at, units.label("units"),
               count("resident").label("residents"), count("collaborator").label("collaborators"),
               count("visitor").label("visitors"))
        .outerjoin(Person, Person.condominium_id == Condominium.id)
        .group_by(Condominium.id)
    )


@app.get("/condominios", response_model=list[CondominiumOut], tags=["condomínios"])
def list_condominiums(session: SessionDep):
    rows = session.execute(_condo_query().order_by(Condominium.name)).mappings()
    return [CondominiumOut(**r) for r in rows]


@app.get("/condominios/{condominium_id}", response_model=CondominiumOut, tags=["condomínios"])
def get_condominium(condominium_id: int, session: SessionDep):
    row = session.execute(_condo_query().where(Condominium.id == condominium_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Condomínio não encontrado")
    return CondominiumOut(**row)


@app.get("/condominios/{condominium_id}/unidades", response_model=list[UnitOut], tags=["condomínios"])
def list_units(condominium_id: int, session: SessionDep):
    get_condominium(condominium_id, session)  # 404 se não existir
    return session.scalars(
        select(Unit).where(Unit.condominium_id == condominium_id).order_by(Unit.block, Unit.unity)
    ).all()


# ----------------------------------------------------------------- pessoas
def _person_out(p: Person, unit: str | None, hoje: date) -> PersonOut:
    return PersonOut(
        id=p.id, gear_id=p.gear_id, kind=p.kind, condominium_id=p.condominium_id, unit_id=p.unit_id,
        unit=unit, full_name=p.full_name, cpf_masked=mask_cpf(p.cpf), permission=p.permission,
        blocked=p.blocked, start_date=p.start_date, expiration_date=p.expiration_date,
        expired=None if p.expiration_date is None else p.expiration_date < hoje,
    )


@app.get("/pessoas", response_model=Page[PersonOut], tags=["pessoas"])
def list_persons(
    session: SessionDep,
    tipo: Kind | None = None,
    condominio_id: int | None = None,
    busca: Annotated[str | None, Query(min_length=2, description="Parte do nome")] = None,
    vencido: bool | None = None,
    funcionario_do_condominio: Annotated[bool | None, Query(
        description="Só colaboradores: true = funcionários do prédio, false = ligados a apartamentos")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    hoje = date.today()
    filtros = []
    if tipo:
        filtros.append(Person.kind == tipo)
    if condominio_id:
        filtros.append(Person.condominium_id == condominio_id)
    if busca:
        filtros.append(Person.full_name.ilike(f"%{busca}%"))
    if vencido is True:
        filtros.append(Person.expiration_date < hoje)
    elif vencido is False:
        filtros.append((Person.expiration_date >= hoje) | Person.expiration_date.is_(None))
    if funcionario_do_condominio is not None:
        filtros += [Person.kind == "collaborator", Unit.is_condominium.is_(funcionario_do_condominio)]

    base = select(Person, Unit.full_unity).outerjoin(Unit, Unit.id == Person.unit_id).where(*filtros)
    total = session.scalar(select(func.count()).select_from(base.subquery()))
    rows = session.execute(
        base.order_by(Person.full_name, Person.id).offset((page - 1) * size).limit(size)
    ).all()
    return Page(total=total, page=page, size=size, items=[_person_out(p, u, hoje) for p, u in rows])


@app.get("/pessoas/{person_id}", response_model=PersonOut, tags=["pessoas"])
def get_person(person_id: int, session: SessionDep):
    row = session.execute(
        select(Person, Unit.full_unity).outerjoin(Unit, Unit.id == Person.unit_id).where(Person.id == person_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Pessoa não encontrada")
    return _person_out(row[0], row[1], date.today())


# --------------------------------------------------------------- relatórios
@app.get("/relatorios/cpf-duplicado", response_model=list[DuplicateCpfOut], tags=["relatórios"])
def duplicated_cpf(session: SessionDep, minimo: Annotated[int, Query(ge=2)] = 2):
    """CPFs com mais de um cadastro (mesma pessoa em vários condomínios/unidades)."""
    dup = (select(Person.cpf).where(func.length(Person.cpf) == 11)
           .group_by(Person.cpf).having(func.count() >= minimo).subquery())
    rows = session.execute(
        select(Person.cpf, Person.condominium_id, Person.full_name)
        .where(Person.cpf.in_(select(dup.c.cpf))).order_by(Person.cpf)
    ).all()
    agrupado: dict[str, list] = {}
    for cpf, cid, nome in rows:
        agrupado.setdefault(cpf, []).append((cid, nome))
    return [
        DuplicateCpfOut(cpf_masked=mask_cpf(cpf), registrations=len(v),
                        condominiums=sorted({c for c, _ in v}), names=sorted({n for _, n in v if n}))
        for cpf, v in agrupado.items()
    ]


@app.get("/relatorios/vencidos", tags=["relatórios"])
def expired_summary(session: SessionDep):
    """Quantidade de cadastros vencidos por condomínio e tipo."""
    rows = session.execute(
        select(Condominium.id, Condominium.name, Person.kind, func.count())
        .join(Person, Person.condominium_id == Condominium.id)
        .where(Person.expiration_date < date.today())
        .group_by(Condominium.id, Condominium.name, Person.kind)
        .order_by(Condominium.name)
    ).all()
    out: dict[int, dict] = {}
    for cid, nome, kind, n in rows:
        item = out.setdefault(cid, {"condominium_id": cid, "name": nome, "total": 0})
        item[kind] = n
        item["total"] += n
    return list(out.values())


# --------------------------------------------------------------------- sync
@app.get("/sync/ultima", response_model=SyncRunOut, tags=["sync"])
def last_sync(session: SessionDep):
    run = session.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(1)).first()
    if run is None:
        raise HTTPException(404, "Nenhuma sincronização executada ainda")
    return run
