"""Testes do cliente GEAR.

Nenhum teste acessa a internet: o `respx` intercepta as chamadas do httpx e
devolve respostas que nós definimos. Assim testamos o comportamento do cliente
(retry, erros, rate limit) de forma rápida e repetível, sem token.
"""
import httpx
import pytest
import respx

from gear_sync.client import GearAPIError, GearClient, RateLimitExceeded, as_list

BASE = "https://gear.test/api"


class FakeTime:
    """Relógio falso: `sleep` só avança o relógio, não espera de verdade."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time():
    return FakeTime()


@pytest.fixture
def client(fake_time):
    with GearClient("abc123", base_url=BASE, min_interval=1.0,
                    sleep=fake_time.sleep, clock=fake_time.clock) as c:
        yield c


# ------------------------------------------------------------------- as_list
@pytest.mark.parametrize("data, esperado", [
    ([1, 2], [1, 2]),
    ({"data": [1, 2]}, [1, 2]),
    ({"total": 2, "items": [3]}, [3]),
    (None, []),
    ({"sem": "lista"}, []),
])
def test_as_list(data, esperado):
    assert as_list(data) == esperado


# ----------------------------------------------------------------- requisição
@respx.mock
def test_envia_token_bearer(client):
    rota = respx.get(f"{BASE}/condominiums").mock(return_value=httpx.Response(200, json=[]))

    client.condominiums()

    assert rota.called
    assert rota.calls.last.request.headers["Authorization"] == "Bearer abc123"


def test_remove_prefixo_bearer_duplicado():
    c = GearClient("Bearer xyz", base_url=BASE)
    assert c._http.headers["Authorization"] == "Bearer xyz"


@respx.mock
def test_condominiums_devolve_lista(client):
    respx.get(f"{BASE}/condominiums").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "condominium": "Ed. Teste"}])
    )
    assert client.condominiums() == [{"id": 1, "condominium": "Ed. Teste"}]


@respx.mock
def test_persons_resposta_inesperada_vira_dict_vazio(client):
    respx.get(f"{BASE}/condominium/7/persons").mock(return_value=httpx.Response(200, json=[]))
    assert client.persons(7) == {}


# --------------------------------------------------------------- rate limit
@respx.mock
def test_respeita_intervalo_minimo(client, fake_time):
    respx.get(f"{BASE}/condominiums").mock(return_value=httpx.Response(200, json=[]))

    client.condominiums()
    client.condominiums()

    # 1ª chamada não espera; a 2ª espera o intervalo inteiro (relógio parado)
    assert fake_time.sleeps == [1.0]


@respx.mock
def test_429_espera_e_tenta_de_novo(client, fake_time):
    respx.get(f"{BASE}/condominiums").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "10"}, text="calma"),
        httpx.Response(200, json=[{"id": 1}]),
    ])

    assert client.condominiums() == [{"id": 1}]
    assert 11 in fake_time.sleeps  # 10s pedidos pela API + 1s de folga
    assert client.calls == 2


@respx.mock
def test_429_com_espera_longa_desiste(client):
    respx.get(f"{BASE}/condominiums").mock(
        return_value=httpx.Response(429, headers={"RateLimit-Reset": "3600"})
    )
    with pytest.raises(RateLimitExceeded):
        client.condominiums()


@respx.mock
def test_429_repetido_esgota_tentativas(client):
    rota = respx.get(f"{BASE}/condominiums").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"})
    )
    with pytest.raises(RateLimitExceeded):
        client.condominiums()
    assert rota.call_count == 3


# --------------------------------------------------------------------- erros
@respx.mock
def test_erro_http_vira_excecao_com_detalhes(client):
    respx.get(f"{BASE}/condominium/99/units").mock(
        return_value=httpx.Response(404, json={"message": "não encontrado"})
    )
    with pytest.raises(GearAPIError) as erro:
        client.units(99)

    assert erro.value.status == 404
    assert erro.value.body == {"message": "não encontrado"}


def test_from_env_sem_token_falha(monkeypatch):
    monkeypatch.delenv("GEAR_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GEAR_TOKEN"):
        GearClient.from_env()


def test_from_env_le_variaveis(monkeypatch):
    monkeypatch.setenv("GEAR_TOKEN", "tok")
    monkeypatch.setenv("GEAR_BASE_URL", BASE)
    monkeypatch.setenv("GEAR_MIN_INTERVAL", "0.5")
    c = GearClient.from_env()
    assert c.min_interval == 0.5
    assert str(c._http.base_url) == BASE + "/"
