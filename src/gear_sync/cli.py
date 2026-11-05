"""Linha de comando.

    gear-sync sync [--limite N]          sincroniza API GEAR → banco
    gear-sync exportar [--saida pasta]   gera CSVs + XLSX a partir do banco
"""
from __future__ import annotations

import argparse
import csv
import logging
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from .client import GearClient
from .db import SessionLocal
from .models import Person, Unit
from .sync import run_sync

DAYS_PT = {"monday": "seg", "tuesday": "ter", "wednesday": "qua", "thursday": "qui",
           "friday": "sex", "saturday": "sab", "sunday": "dom"}
COLS = ["tipo", "id_condominio", "id_unidade", "unidade", "id_pessoa", "nome", "cpf", "rg", "nascimento",
        "celular", "email", "permissao", "bloqueado", "data_inicio", "data_fim", "vencido",
        "hora_inicio", "hora_fim"] + [f"{a}_{s}" for a in DAYS_PT.values() for s in ("permitido", "inicio", "fim")]


def cmd_sync(args) -> None:
    with GearClient.from_env() as client, SessionLocal() as session:
        r = run_sync(session, client, limit=args.limite)
    print(f"{r.condominiums} condomínios, {r.units} unidades, {r.persons} pessoas, "
          f"{r.removed} removidas, {len(r.errors)} erros")


def _rows(session):
    hoje = date.today()
    q = select(Person, Unit.full_unity, Unit.is_condominium).outerjoin(Unit, Unit.id == Person.unit_id)
    for p, unidade, do_condominio in session.execute(q.order_by(Person.condominium_id, Person.full_name)):
        tipo = {"resident": "MORADOR", "visitor": "VISITANTE"}.get(
            p.kind, "FUNC_CONDOMINIO" if do_condominio else "FUNC_UNIDADE")
        sched = p.schedule or {}
        dias = []
        for d in DAYS_PT:
            s = sched.get(d) or {}
            dias += [s.get("allowed"), s.get("start"), s.get("end")]
        yield [tipo, p.condominium_id, p.unit_id, unidade, p.gear_id, p.full_name, p.cpf, p.rg, p.birthday,
               p.cell_number, p.email, p.permission, p.blocked, p.start_date, p.expiration_date,
               None if p.expiration_date is None else p.expiration_date < hoje,
               p.start_hour, p.end_hour, *dias]


def cmd_export(args) -> None:
    from openpyxl import Workbook

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    carimbo = f"{datetime.now():%Y%m%d_%H%M}"
    with SessionLocal() as session:
        linhas = list(_rows(session))

    csv_path = saida / f"GEAR_Pessoas_{carimbo}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: abre certo no Excel
        w = csv.writer(f, delimiter=";")
        w.writerow(COLS)
        w.writerows(linhas)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("pessoas")
    ws.append(COLS)
    for r in linhas:
        ws.append(r)
    xlsx_path = saida / f"GEAR_Pessoas_{carimbo}.xlsx"
    wb.save(xlsx_path)
    print(f"{len(linhas)} linhas → {csv_path} e {xlsx_path}")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="gear-sync")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="sincroniza a API GEAR com o banco")
    s.add_argument("--limite", type=int, default=None, help="só os N primeiros condomínios (teste)")
    s.set_defaults(func=cmd_sync)
    e = sub.add_parser("exportar", help="exporta as pessoas do banco para CSV e XLSX")
    e.add_argument("--saida", default="exportacao")
    e.set_defaults(func=cmd_export)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
