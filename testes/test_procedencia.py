"""
Testes da procedência dos dados e da assinatura do esquema.

Cobrem dois riscos que não aparecem em teste de acurácia:

  - apresentar número obtido com dados sintéticos como se fosse real;
  - usar um modelo antigo depois que o formato dos dados mudou.
"""

import json

import pytest

from src import esquema, procedencia


@pytest.fixture
def csv_temporario(tmp_path, monkeypatch):
    """Um CSV qualquer e um registro de procedência isolados do projeto."""
    caminho = tmp_path / "dados.csv"
    caminho.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(
        procedencia, "ARQUIVO_PROCEDENCIA", tmp_path / "procedencia.json"
    )
    return caminho


def test_sem_registro_a_origem_e_desconhecida(csv_temporario):
    resultado = procedencia.identificar(csv_temporario)
    assert resultado["origem"] == procedencia.DESCONHECIDA
    assert resultado["aviso"] is None


def test_registro_marca_o_arquivo_como_sintetico(csv_temporario):
    procedencia.registrar_sintetico(csv_temporario, semente=42, anos=(2015, 2024), linhas=1)

    resultado = procedencia.identificar(csv_temporario)
    assert resultado["origem"] == procedencia.SINTETICO
    assert "SINTÉTICOS" in resultado["aviso"]
    assert procedencia.e_sintetico(csv_temporario)


def test_csv_trocado_deixa_de_ser_sintetico(csv_temporario):
    """
    O ponto central: se alguém substituir o CSV pela base real mantendo o
    mesmo nome, o registro antigo não pode continuar valendo.
    """
    procedencia.registrar_sintetico(csv_temporario, semente=42, anos=(2015, 2024), linhas=1)
    assert procedencia.e_sintetico(csv_temporario)

    csv_temporario.write_text("a,b\n9,9\n", encoding="utf-8")

    assert not procedencia.e_sintetico(csv_temporario)
    assert procedencia.identificar(csv_temporario)["origem"] == procedencia.DESCONHECIDA


def test_registro_corrompido_nao_quebra(csv_temporario):
    procedencia.ARQUIVO_PROCEDENCIA.write_text("{isso não é json", encoding="utf-8")
    assert procedencia.identificar(csv_temporario)["origem"] == procedencia.DESCONHECIDA


def test_hash_muda_quando_o_conteudo_muda(csv_temporario):
    antes = procedencia.hash_arquivo(csv_temporario)
    csv_temporario.write_text("a,b\n7,7\n", encoding="utf-8")
    assert procedencia.hash_arquivo(csv_temporario) != antes


def test_registro_e_json_legivel(csv_temporario):
    caminho = procedencia.registrar_sintetico(
        csv_temporario, semente=7, anos=(2020, 2021), linhas=1
    )
    registro = json.loads(caminho.read_text(encoding="utf-8"))
    assert registro["origem"] == procedencia.SINTETICO
    assert registro["semente"] == 7
    assert registro["periodo"] == {"ano_inicial": 2020, "ano_final": 2021}


# --------------------------------------------------------------------------
# Assinatura do esquema
# --------------------------------------------------------------------------


def test_assinatura_e_estavel():
    assert esquema.assinatura() == esquema.assinatura()


def test_assinatura_muda_quando_uma_coluna_e_adicionada(monkeypatch):
    original = esquema.assinatura()
    monkeypatch.setattr(
        esquema,
        "COLUNAS_MODELO_NUMERICAS",
        esquema.COLUNAS_MODELO_NUMERICAS + ["coluna_nova"],
    )
    assert esquema.assinatura() != original


def test_assinatura_muda_quando_as_classes_mudam(monkeypatch):
    original = esquema.assinatura()
    monkeypatch.setattr(esquema, "CLASSES_RISCO", ["baixo", "alto"])
    assert esquema.assinatura() != original


# --------------------------------------------------------------------------
# A API precisa recusar um modelo treinado com outro formato de dados
# --------------------------------------------------------------------------


def test_api_recusa_modelo_de_esquema_diferente(monkeypatch):
    """
    Simula o cenário real: alguém muda as colunas em src/esquema.py, dá
    `git pull` e esquece de retreinar. O modelo antigo não pode responder.
    """
    app_backend = pytest.importorskip("backend.app")

    if not app_backend.ARQUIVO_MODELO.exists():
        pytest.skip("modelo não treinado — rode: python treinamento/treinar_modelo.py")

    monkeypatch.setattr(esquema, "assinatura", lambda: "assinatura_diferente")

    try:
        assert app_backend.carregar_modelo() is False
        assert app_backend.modelo is None
        assert "Retreine" in app_backend.problema_modelo
    finally:
        # Restaura o estado real do módulo para não afetar os outros testes.
        monkeypatch.undo()
        app_backend.carregar_modelo()
