"""Conversão dos JSONs da API GEAR para linhas do banco (funções puras, fáceis de testar)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
KIND_BY_KEY = {"residents": "resident", "collaborators": "collaborator", "visitors": "visitor"}


def norm(s: Any) -> str:
    """Minúsculas, sem acento e sem espaços nas pontas."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.strip().lower()


def clean(s: Any) -> str | None:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def parse_date(s: Any) -> date | None:
    """'2024-05-01' (ou '2024-05-01T10:00') → date. Inválida ou anterior a 1900 → None."""
    try:
        d = datetime.strptime(str(s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return d if d.year >= 1900 else None


def parse_hour(s: Any) -> str | None:
    """'08:00' ou '08:00:00' → '08:00'."""
    m = re.match(r"^(\d{2}):(\d{2})", str(s or ""))
    return f"{m[1]}:{m[2]}" if m else None


def only_digits(s: Any) -> str | None:
    d = re.sub(r"\D", "", str(s or ""))
    return d or None


def valid_cpf(cpf: str | None) -> bool:
    """Valida os dígitos verificadores do CPF."""
    if not cpf or len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        if (total * 10 % 11) % 10 != int(cpf[size]):
            return False
    return True


def mask_cpf(cpf: str | None) -> str | None:
    """'12345678901' → '***.456.789-**' (LGPD: a API REST nunca devolve o CPF inteiro)."""
    if not cpf or len(cpf) != 11:
        return None
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**"


def is_condominium_unit(u: dict) -> bool:
    """Unidade que representa o próprio condomínio ("Condomínio", "00", "Administração"...)."""
    text = " ".join(norm(u.get(k)) for k in ("block", "unity", "full_unity", "description"))
    name = norm(u.get("unity"))
    return ("condominio" in text or name in ("0", "00", "000")
            or any(p in name for p in ("administra", "colaborador", "zeladoria")))


def condominium_row(c: dict) -> dict:
    return {
        "id": int(c["id"]),
        "name": clean(c.get("condominium") or c.get("name")) or f"Condomínio {c['id']}",
        "id_integration": clean(c.get("id_integration")),
    }


def unit_row(u: dict, condominium_id: int) -> dict:
    return {
        "id": int(u["id"]),
        "condominium_id": condominium_id,
        "block": clean(u.get("block")),
        "unity": clean(u.get("unity")),
        "full_unity": clean(u.get("full_unity")),
        "description": clean(u.get("description")),
        "is_condominium": is_condominium_unit(u),
    }


def schedule(p: dict) -> dict | None:
    if not any(f"flg_{d}" in p for d in DAYS):
        return None
    return {
        d: {"allowed": bool(p.get(f"flg_{d}")),
            "start": parse_hour(p.get(f"time_{d}_start")),
            "end": parse_hour(p.get(f"time_{d}_end"))}
        for d in DAYS
    }


def person_row(p: dict, kind: str, condominium_id: int) -> dict:
    return {
        "kind": kind,
        "gear_id": int(p["id"]),
        "condominium_id": condominium_id,
        "unit_id": p.get("id_unity"),
        "full_name": clean(p.get("full_name")) or clean(f"{p.get('name') or ''} {p.get('last_name') or ''}"),
        "cpf": only_digits(p.get("cpf_number")),
        "rg": clean(p.get("rg_number")),
        "birthday": parse_date(p.get("birthday")),
        "cell_number": clean(p.get("cell_number")),
        "cell_number_2": clean(p.get("cell_number_2")),
        "email": clean(p.get("email")),
        "permission": p.get("permission"),
        "blocked": p.get("block"),  # no GEAR, "block" da pessoa = flag de bloqueio
        "start_date": parse_date(p.get("start_date")),
        "expiration_date": parse_date(p.get("expiration_date")),
        "start_hour": parse_hour(p.get("start_hour")),
        "end_hour": parse_hour(p.get("end_hour")),
        "schedule": schedule(p),
        "description": clean(p.get("description")),
        "id_integration": clean(p.get("id_integration")),
        "photo_url": clean(p.get("photo_url")),
    }


def person_rows(persons: dict, condominium_id: int) -> list[dict]:
    rows = []
    for key, kind in KIND_BY_KEY.items():
        for p in persons.get(key) or []:
            if p.get("id") is not None:
                rows.append(person_row(p, kind, condominium_id))
    return rows
