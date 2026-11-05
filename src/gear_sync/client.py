"""Cliente HTTP da API Pública GEAR (somente leitura).

Responsabilidades:
- autenticar com Bearer token;
- respeitar o limite de requisições (intervalo mínimo entre chamadas);
- em HTTP 429, esperar o tempo indicado pela API e tentar de novo;
- transformar erros HTTP em exceções Python com mensagem clara.

`sleep` e `clock` são injetáveis para que os testes rodem sem esperar de verdade.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.gear-tecnorise.com/api"


class GearAPIError(Exception):
    """A API respondeu com um erro (4xx/5xx) que não vale a pena repetir."""

    def __init__(self, status: int, body: Any, path: str):
        self.status, self.body, self.path = status, body, path
        super().__init__(f"GEAR {path} -> HTTP {status}: {body}")


class RateLimitExceeded(GearAPIError):
    """Limite de requisições estourado e a espera pedida pela API é longa demais."""


def as_list(data: Any) -> list:
    """Extrai a lista de registros de uma resposta, seja lista pura ou embrulhada num objeto."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


class GearClient:
    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        min_interval: float = 1.1,
        max_retries: int = 3,
        max_wait: float = 120,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        http_client: httpx.Client | None = None,
    ):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.max_wait = max_wait
        self._sleep, self._clock = sleep, clock
        self._last_call = float("-inf")
        self.calls = 0
        self.remaining: str | None = None
        # `http_client` permite plugar outro cliente httpx (ex.: TestClient do servidor GEAR falso)
        self._http = http_client or httpx.Client(base_url=base_url.rstrip("/"), timeout=30,
                                                 transport=transport)
        self._http.headers.update({
            "Authorization": f"Bearer {token.removeprefix('Bearer ').strip()}",
            "Accept": "application/json",
        })

    @classmethod
    def from_env(cls, **kwargs) -> GearClient:
        token = os.environ.get("GEAR_TOKEN")
        if not token:
            raise RuntimeError("Defina a variável de ambiente GEAR_TOKEN (veja .env.example).")
        return cls(
            token,
            base_url=os.environ.get("GEAR_BASE_URL", DEFAULT_BASE_URL),
            min_interval=float(os.environ.get("GEAR_MIN_INTERVAL", 1.1)),
            **kwargs,
        )

    # ------------------------------------------------------------------ núcleo
    def _throttle(self) -> None:
        """Garante pelo menos `min_interval` segundos entre duas chamadas."""
        wait = self.min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def get(self, path: str, params: dict | None = None) -> Any:
        for _attempt in range(self.max_retries):
            self._throttle()
            self.calls += 1
            resp = self._http.get(path, params=params)
            self.remaining = resp.headers.get("RateLimit-Remaining", self.remaining)

            if resp.status_code == 429:
                delay = float(resp.headers.get("RateLimit-Reset") or resp.headers.get("Retry-After") or 5)
                if delay > self.max_wait:
                    raise RateLimitExceeded(429, resp.text, path)
                self._sleep(delay + 1)
                continue

            if resp.is_error:
                try:
                    body = resp.json()
                except ValueError:
                    body = resp.text
                raise GearAPIError(resp.status_code, body, path)

            return resp.json() if resp.content else None

        raise RateLimitExceeded(429, "limite excedido em todas as tentativas", path)

    # ------------------------------------------------------------- endpoints
    def condominiums(self) -> list[dict]:
        return as_list(self.get("/condominiums"))

    def units(self, condominium_id: int) -> list[dict]:
        return as_list(self.get(f"/condominium/{condominium_id}/units"))

    def persons(self, condominium_id: int) -> dict[str, list[dict]]:
        """Retorna {"residents": [...], "collaborators": [...], "visitors": [...]}."""
        data = self.get(f"/condominium/{condominium_id}/persons")
        return data if isinstance(data, dict) else {}

    # --------------------------------------------------------- context manager
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GearClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
