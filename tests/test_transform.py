from datetime import date

import pytest

from gear_sync import transform as t


@pytest.mark.parametrize("entrada, esperado", [
    ("2024-05-01", date(2024, 5, 1)),
    ("2024-05-01T10:30", date(2024, 5, 1)),
    ("0000-00-00", None),
    ("1800-01-01", None),
    ("", None),
    (None, None),
])
def test_parse_date(entrada, esperado):
    assert t.parse_date(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    ("08:00", "08:00"), ("23:59:00", "23:59"), ("8h", None), (None, None),
])
def test_parse_hour(entrada, esperado):
    assert t.parse_hour(entrada) == esperado


def test_only_digits():
    assert t.only_digits("123.456.789-09") == "12345678909"
    assert t.only_digits("") is None


@pytest.mark.parametrize("cpf, valido", [
    ("52998224725", True),
    ("52998224724", False),  # dígito verificador errado
    ("11111111111", False),  # todos iguais
    ("123", False),
    (None, False),
])
def test_valid_cpf(cpf, valido):
    assert t.valid_cpf(cpf) is valido


def test_mask_cpf():
    assert t.mask_cpf("52998224725") == "***.982.247-**"
    assert t.mask_cpf("123") is None


@pytest.mark.parametrize("unidade, esperado", [
    ({"unity": "00", "block": ""}, True),
    ({"unity": "Administração"}, True),
    ({"unity": "1", "full_unity": "Condomínio"}, True),
    ({"unity": "101", "block": "Bloco A"}, False),
])
def test_is_condominium_unit(unidade, esperado):
    assert t.is_condominium_unit(unidade) is esperado


def test_person_row_converte_e_ignora_senha():
    p = {"id": 5, "id_unity": 10, "full_name": "  Ana Souza ", "cpf_number": "529.982.247-25",
         "birthday": "1990-02-03", "expiration_date": "", "start_hour": "07:00:00", "block": True,
         "password_access": "1234", "flg_monday": True, "time_monday_start": "08:00", "time_monday_end": "17:00"}

    row = t.person_row(p, "collaborator", 99)

    assert row["full_name"] == "Ana Souza"
    assert row["cpf"] == "52998224725"
    assert row["birthday"] == date(1990, 2, 3)
    assert row["expiration_date"] is None
    assert row["start_hour"] == "07:00"
    assert row["blocked"] is True
    assert row["schedule"]["monday"] == {"allowed": True, "start": "08:00", "end": "17:00"}
    assert row["schedule"]["sunday"]["allowed"] is False
    assert "password_access" not in row


def test_person_row_monta_nome_quando_full_name_vazio():
    row = t.person_row({"id": 1, "name": "Ana", "last_name": "Lima"}, "resident", 1)
    assert row["full_name"] == "Ana Lima"
    assert row["schedule"] is None  # morador não tem grade de horário


def test_person_rows_ignora_registro_sem_id():
    persons = {"residents": [{"id": 1}, {"id": None}], "visitors": [{"id": 2}]}
    rows = t.person_rows(persons, 1)
    assert [(r["kind"], r["gear_id"]) for r in rows] == [("resident", 1), ("visitor", 2)]
