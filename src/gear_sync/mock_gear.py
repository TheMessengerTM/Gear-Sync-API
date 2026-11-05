"""Servidor GEAR FALSO, com dados fictícios gerados pelo Faker.

Imita o formato das respostas da API Pública GEAR para que qualquer pessoa
rode o projeto (e os testes) sem token e sem dados reais.

    uvicorn gear_sync.mock_gear:app --port 8001
    GEAR_BASE_URL=http://localhost:8001/api  GEAR_TOKEN=qualquer  gear-sync sync

Variáveis: MOCK_SEED (padrão 42) e MOCK_CONDOS (padrão 5).
"""
from __future__ import annotations

import os
import random
from datetime import date, timedelta

from faker import Faker
from fastapi import FastAPI, Header, HTTPException, Request

from .transform import DAYS


def _person(fake: Faker, rnd: random.Random, pid: int, unit_id: int, kind: str) -> dict:
    hoje = date.today()
    inicio = fake.date_between(hoje - timedelta(days=900), hoje - timedelta(days=30))
    # ~15% com cadastro vencido, para o relatório de vencidos ter conteúdo
    if rnd.random() < 0.15:
        fim = hoje - timedelta(days=rnd.randint(1, 200))
    else:
        fim = hoje + timedelta(days=rnd.randint(30, 900))
    nome, sobrenome = fake.first_name(), fake.last_name()
    p = {
        "id": pid,
        "id_unity": unit_id,
        "id_integration": None,
        "name": nome,
        "last_name": sobrenome,
        "full_name": f"{nome} {sobrenome}",
        "cell_number": fake.cellphone_number() if kind != "visitor" else None,
        "cell_number_2": None,
        "cpf_number": fake.cpf() if kind != "visitor" else None,
        "rg_number": fake.rg() if kind != "visitor" else None,
        "email": fake.free_email() if kind == "resident" else None,
        "photo_url": f"https://fotos.exemplo/{pid}.jpg",
        "password_access": "1234" if kind == "resident" else None,  # o sync deve IGNORAR este campo
        "against_password_access": None,
        "block": rnd.random() < 0.05,
        "permission": rnd.random() > 0.1,
        "birthday": fake.date_of_birth(minimum_age=18, maximum_age=85).isoformat(),
        "start_date": inicio.isoformat(),
        "expiration_date": fim.isoformat(),
        "start_hour": "00:00",
        "end_hour": rnd.choice(["23:59", "23:59:00"]),
        "description": "Prestador de serviço" if kind == "visitor" else None,
    }
    if kind != "resident":
        for d in DAYS:
            util = d not in ("saturday", "sunday")
            p[f"flg_{d}"] = util
            p[f"time_{d}_start"] = "08:00" if util else None
            p[f"time_{d}_end"] = "18:00" if util else None
    return p


def build_dataset(seed: int = 42, n_condos: int = 5) -> dict:
    fake = Faker("pt_BR")
    fake.seed_instance(seed)
    rnd = random.Random(seed)
    next_id = iter(range(1000, 10**9))

    condos, units, persons = [], {}, {}
    for c in range(n_condos):
        cid = 9000 + c
        condos.append({"id": cid, "id_integration": c + 1, "condominium": f"Residencial {fake.last_name()}"})
        us = [{"id": next(next_id), "full_unity": "Condomínio", "unity": "00", "block": "",
               "id_integration": None, "number_concierge_autonomous": None, "description": "Condomínio"}]
        for bloco in "AB"[: rnd.randint(1, 2)]:
            for andar in range(1, rnd.randint(3, 5)):
                for apto in (1, 2):
                    nome = f"{andar}{apto:02d}"
                    us.append({"id": next(next_id), "full_unity": f"Bloco {bloco} - {nome}", "unity": nome,
                               "block": f"Bloco {bloco}", "id_integration": None,
                               "number_concierge_autonomous": None, "description": ""})
        units[cid] = us

        ps = {"residents": [], "collaborators": [], "visitors": []}
        for _ in range(rnd.randint(4, 7)):  # funcionários do prédio (unidade "Condomínio")
            ps["collaborators"].append(_person(fake, rnd, next(next_id), us[0]["id"], "collaborator"))
        for u in us[1:]:
            for _ in range(rnd.randint(1, 3)):
                ps["residents"].append(_person(fake, rnd, next(next_id), u["id"], "resident"))
            if rnd.random() < 0.3:  # diarista/babá ligada ao apartamento
                ps["collaborators"].append(_person(fake, rnd, next(next_id), u["id"], "collaborator"))
            if rnd.random() < 0.2:
                ps["visitors"].append(_person(fake, rnd, next(next_id), u["id"], "visitor"))
        persons[cid] = ps

    # Mesma pessoa cadastrada em dois condomínios (CPF repetido) para o relatório de duplicados
    if n_condos >= 2:
        a, b = persons[condos[0]["id"]]["residents"][0], persons[condos[1]["id"]]["residents"][0]
        b["cpf_number"], b["full_name"] = a["cpf_number"], a["full_name"]

    return {"condominiums": condos, "units": units, "persons": persons}


def create_app(dataset: dict | None = None) -> FastAPI:
    app = FastAPI(title="GEAR (falso)", description="Imitação da API Pública GEAR com dados fictícios.")
    app.state.data = dataset or build_dataset(int(os.environ.get("MOCK_SEED", 42)),
                                              int(os.environ.get("MOCK_CONDOS", 5)))

    def auth(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) < 8:
            raise HTTPException(401, "Token ausente ou inválido")

    def condo_or_404(request: Request, cid: int):
        if cid not in request.app.state.data["units"]:
            raise HTTPException(404, "Condomínio não encontrado")

    @app.get("/api/condominiums")
    def condominiums(request: Request, authorization: str | None = Header(None)):
        auth(authorization)
        return request.app.state.data["condominiums"]

    @app.get("/api/condominium/{cid}/units")
    def units(cid: int, request: Request, authorization: str | None = Header(None)):
        auth(authorization)
        condo_or_404(request, cid)
        return request.app.state.data["units"][cid]

    @app.get("/api/condominium/{cid}/persons")
    def persons(cid: int, request: Request, authorization: str | None = Header(None)):
        auth(authorization)
        condo_or_404(request, cid)
        return request.app.state.data["persons"][cid]

    return app


app = create_app()
