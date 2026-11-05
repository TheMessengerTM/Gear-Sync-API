"""Testes da API REST: sincroniza dados falsos no banco de teste e consulta os endpoints."""
import pytest
from fastapi.testclient import TestClient

from gear_sync.api import app
from gear_sync.db import get_session
from gear_sync.sync import run_sync


@pytest.fixture
def api(session, gear):
    run_sync(session, gear)
    app.dependency_overrides[get_session] = lambda: session  # API usa o banco de teste
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_lista_condominios_com_contagens(api, dataset):
    r = api.get("/condominios")
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 3
    c = next(x for x in corpo if x["id"] == dataset["condominiums"][0]["id"])
    assert c["residents"] == len(dataset["persons"][c["id"]]["residents"])
    assert c["units"] == len(dataset["units"][c["id"]])


def test_condominio_inexistente_404(api):
    assert api.get("/condominios/1").status_code == 404
    assert api.get("/condominios/1/unidades").status_code == 404


def test_unidades_do_condominio(api, dataset):
    cid = dataset["condominiums"][0]["id"]
    unidades = api.get(f"/condominios/{cid}/unidades").json()
    assert len(unidades) == len(dataset["units"][cid])
    assert sum(u["is_condominium"] for u in unidades) == 1


def test_pessoas_paginacao(api, dataset):
    r = api.get("/pessoas", params={"size": 5, "page": 2}).json()
    assert r["page"] == 2 and r["size"] == 5
    assert len(r["items"]) == 5
    assert r["total"] == sum(len(v) for ps in dataset["persons"].values() for v in ps.values())


def test_pessoas_nunca_expoem_cpf_completo(api):
    itens = api.get("/pessoas", params={"tipo": "resident", "size": 200}).json()["items"]
    assert itens
    for p in itens:
        assert "cpf" not in p
        assert p["cpf_masked"] is None or p["cpf_masked"].startswith("***.")


def test_filtros_de_pessoas(api):
    vencidos = api.get("/pessoas", params={"vencido": True, "size": 200}).json()["items"]
    assert vencidos and all(p["expired"] for p in vencidos)

    func = api.get("/pessoas", params={"funcionario_do_condominio": True, "size": 200}).json()["items"]
    assert func and all(p["kind"] == "collaborator" and p["unit"] == "Condomínio" for p in func)

    nome = vencidos[0]["full_name"].split()[0]
    busca = api.get("/pessoas", params={"busca": nome}).json()["items"]
    assert all(nome.lower() in p["full_name"].lower() for p in busca)


def test_parametro_invalido_retorna_422(api):
    assert api.get("/pessoas", params={"tipo": "gato"}).status_code == 422
    assert api.get("/pessoas", params={"size": 1000}).status_code == 422


def test_pessoa_por_id(api):
    primeira = api.get("/pessoas", params={"size": 1}).json()["items"][0]
    assert api.get(f"/pessoas/{primeira['id']}").json() == primeira
    assert api.get("/pessoas/999999").status_code == 404


def test_relatorio_cpf_duplicado(api, dataset):
    dup = api.get("/relatorios/cpf-duplicado").json()
    assert len(dup) == 1  # o servidor falso repete 1 CPF entre os 2 primeiros condomínios
    assert dup[0]["registrations"] == 2
    assert dup[0]["condominiums"] == sorted(c["id"] for c in dataset["condominiums"][:2])


def test_relatorio_vencidos(api):
    rel = api.get("/relatorios/vencidos").json()
    assert rel and all(r["total"] > 0 for r in rel)


def test_ultima_sincronizacao(api):
    r = api.get("/sync/ultima").json()
    assert r["status"] == "ok" and r["condominiums"] == 3
