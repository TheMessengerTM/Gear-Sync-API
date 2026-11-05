"""Sincronização API GEAR → banco.

Para cada condomínio:
  1. busca /units e /persons (2 chamadas);
  2. faz UPSERT (insere o que é novo, atualiza o que já existe) em uma transação;
  3. apaga do banco quem sumiu da API naquele condomínio.

Rodar duas vezes seguidas dá o mesmo resultado (idempotente): nada é duplicado.
Se um condomínio falhar, os outros continuam e o erro fica registrado em sync_runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from . import transform
from .client import GearAPIError, GearClient
from .models import Condominium, Person, SyncRun, Unit

log = logging.getLogger(__name__)


def upsert(session: Session, model, rows: list[dict], conflict_cols: list[str]) -> None:
    """INSERT ... ON CONFLICT (conflict_cols) DO UPDATE SET <demais colunas>.

    PostgreSQL e SQLite têm essa sintaxe; o SQLAlchemy gera o SQL certo para cada um.
    """
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    insert = {"postgresql": postgresql.insert, "sqlite": sqlite.insert}.get(dialect)
    if insert is None:
        raise NotImplementedError(f"upsert não implementado para {dialect}")

    stmt = insert(model).values(rows)
    update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in conflict_cols}
    update_cols["synced_at"] = func.now()
    session.execute(stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols))


def chunks(rows: list[dict], size: int = 500):
    """Divide em lotes (o SQLite limita a quantidade de parâmetros por comando)."""
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


@dataclass
class SyncReport:
    condominiums: int = 0
    units: int = 0
    persons: int = 0
    removed: int = 0
    errors: list[dict] = field(default_factory=list)


def sync_condominium(session: Session, client: GearClient, condo: dict, report: SyncReport) -> None:
    cid = int(condo["id"])
    units = [transform.unit_row(u, cid) for u in client.units(cid) if u.get("id") is not None]
    persons = transform.person_rows(client.persons(cid), cid)

    with session.begin():  # tudo ou nada para este condomínio
        upsert(session, Condominium, [transform.condominium_row(condo)], ["id"])
        for lote in chunks(units):
            upsert(session, Unit, lote, ["id"])
        for lote in chunks(persons):
            upsert(session, Person, lote, ["kind", "gear_id"])

        # Remoção: quem está no banco para este condomínio mas não veio na API
        vindos = {(p["kind"], p["gear_id"]) for p in persons}
        no_banco = {tuple(r) for r in session.execute(
            select(Person.kind, Person.gear_id).where(Person.condominium_id == cid)
        )}
        sumiram = no_banco - vindos
        if sumiram:
            session.execute(delete(Person).where(
                Person.condominium_id == cid,
                tuple_(Person.kind, Person.gear_id).in_(sumiram),
            ))
        unit_ids = [u["id"] for u in units]
        session.execute(delete(Unit).where(Unit.condominium_id == cid, Unit.id.not_in(unit_ids)))

    report.condominiums += 1
    report.units += len(units)
    report.persons += len(persons)
    report.removed += len(sumiram)


def run_sync(session: Session, client: GearClient, limit: int | None = None) -> SyncReport:
    report = SyncReport()
    run = SyncRun(started_at=datetime.now(UTC), status="running")
    session.add(run)
    session.commit()
    status = "error"

    try:
        condos = client.condominiums()[:limit]
        for i, condo in enumerate(condos, 1):
            try:
                sync_condominium(session, client, condo, report)
                log.info("[%d/%d] condomínio %s ok", i, len(condos), condo.get("id"))
            except GearAPIError as e:
                session.rollback()
                report.errors.append({"condominium_id": condo.get("id"), "status": e.status, "error": str(e)})
                log.warning("[%d/%d] condomínio %s falhou: %s", i, len(condos), condo.get("id"), e)
        status = "partial" if report.errors else "ok"
    except Exception as e:
        session.rollback()
        report.errors.append({"error": str(e)})
        raise
    finally:
        run.finished_at = datetime.now(UTC)
        run.status = status
        run.condominiums, run.units = report.condominiums, report.units
        run.persons, run.removed = report.persons, report.removed
        run.api_calls, run.errors = client.calls, report.errors or None
        session.add(run)
        session.commit()
    return report
