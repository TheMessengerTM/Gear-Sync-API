"""Testes da linha de comando (sync + exportar), usando o servidor GEAR falso."""
import csv

import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import sessionmaker

from gear_sync import cli


@pytest.fixture
def cli_env(monkeypatch, engine, session, gear):
    """Faz a CLI usar o banco de teste e o servidor falso."""
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(cli.GearClient, "from_env", classmethod(lambda cls: gear))


def test_sync_e_exportar(cli_env, tmp_path, capsys, dataset):
    cli.main(["sync"])
    assert "3 condomínios" in capsys.readouterr().out

    cli.main(["exportar", "--saida", str(tmp_path)])

    csv_file = next(tmp_path.glob("*.csv"))
    with csv_file.open(encoding="utf-8-sig") as f:
        linhas = list(csv.reader(f, delimiter=";"))
    total = sum(len(v) for ps in dataset["persons"].values() for v in ps.values())
    assert linhas[0][:2] == ["tipo", "id_condominio"]
    assert len(linhas) == total + 1
    assert {r[0] for r in linhas[1:]} >= {"MORADOR", "FUNC_CONDOMINIO"}

    ws = load_workbook(next(tmp_path.glob("*.xlsx"))).active
    assert ws.max_row == total + 1
