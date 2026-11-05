"""Testes de integração da sincronização: servidor GEAR falso → banco de teste."""
from sqlalchemy import func, select

from gear_sync.models import Condominium, Person, SyncRun, Unit
from gear_sync.sync import run_sync


def contar(session, model):
    return session.scalar(select(func.count()).select_from(model))


def total_pessoas(dataset):
    return sum(len(v) for ps in dataset["persons"].values() for v in ps.values())


def test_primeira_sincronizacao_grava_tudo(session, gear, dataset):
    report = run_sync(session, gear)

    assert report.errors == []
    assert contar(session, Condominium) == 3
    assert contar(session, Unit) == sum(len(u) for u in dataset["units"].values())
    assert contar(session, Person) == total_pessoas(dataset)
    assert report.persons == total_pessoas(dataset)


def test_sincronizar_duas_vezes_nao_duplica(session, gear, dataset):
    run_sync(session, gear)
    run_sync(session, gear)

    assert contar(session, Person) == total_pessoas(dataset)
    assert contar(session, Condominium) == 3


def test_alteracao_na_api_atualiza_o_banco(session, gear, dataset):
    run_sync(session, gear)
    cid = dataset["condominiums"][0]["id"]
    morador = dataset["persons"][cid]["residents"][0]
    morador["full_name"] = "Nome Alterado"
    dataset["condominiums"][0]["condominium"] = "Edifício Renomeado"

    run_sync(session, gear)

    p = session.scalar(select(Person).where(Person.kind == "resident", Person.gear_id == morador["id"]))
    assert p.full_name == "Nome Alterado"
    assert session.get(Condominium, cid).name == "Edifício Renomeado"


def test_quem_sumiu_da_api_e_removido(session, gear, dataset):
    run_sync(session, gear)
    cid = dataset["condominiums"][0]["id"]
    removido = dataset["persons"][cid]["residents"].pop()

    report = run_sync(session, gear)

    assert report.removed == 1
    assert session.scalar(
        select(Person).where(Person.kind == "resident", Person.gear_id == removido["id"])
    ) is None
    assert contar(session, Person) == total_pessoas(dataset)


def test_unidade_do_condominio_e_marcada(session, gear):
    run_sync(session, gear)
    do_condominio = session.scalars(select(Unit).where(Unit.is_condominium)).all()
    assert len(do_condominio) == 3  # uma por condomínio ("00 - Condomínio")


def test_falha_em_um_condominio_nao_para_os_outros(session, gear, dataset, mock_app):
    quebrado = dataset["condominiums"][1]["id"]
    del mock_app.state.data["units"][quebrado]  # servidor falso passa a responder 404

    report = run_sync(session, gear)

    assert report.condominiums == 2
    assert report.errors[0]["condominium_id"] == quebrado
    run = session.scalar(select(SyncRun))
    assert run.status == "partial"
    assert run.errors and run.errors[0]["status"] == 404


def test_registra_historico_da_sincronizacao(session, gear):
    run_sync(session, gear, limit=1)

    run = session.scalar(select(SyncRun))
    assert run.status == "ok"
    assert run.condominiums == 1
    assert run.api_calls == 3  # /condominiums + /units + /persons
    assert run.finished_at is not None
