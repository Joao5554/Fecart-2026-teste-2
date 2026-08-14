"""
Testes da consulta simplificada — o caminho que a interface web usa.

Aqui o usuário informa só município, tipo e mês; o backend calcula as quinze
variáveis históricas. O ponto crítico é que esse cálculo use exatamente a
mesma função do treino, e é isso que os testes abaixo verificam.
"""

import numpy as np
import pandas as pd
import pytest

from src import atlas, esquema

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import app  # noqa: E402
from backend import app as modulo_app  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

precisa_de_dados = pytest.mark.skipif(
    modulo_app.ocorrencias is None or modulo_app.modelo is None,
    reason="rode: python dados/preparar_dados.py && python treinamento/treinar_modelo.py",
)


# --------------------------------------------------------------------------
# Cálculo das features de uma consulta
# --------------------------------------------------------------------------


def test_features_de_consulta_cobrem_o_esquema(ocorrencias):
    features = atlas.features_para_consulta(
        ocorrencias, 3303906, "DESLIZAMENTO", ano=2026, mes=2
    )
    assert set(features) == set(esquema.COLUNAS_NUMERICAS)

    # As variáveis vindas do Atlas são sempre calculáveis.
    do_atlas = [v for k, v in features.items() if k not in esquema.COLUNAS_CLIMA]
    assert all(np.isfinite(do_atlas))


def test_clima_fica_vazio_quando_nao_ha_medicao(ocorrencias):
    """
    O clima não vem do Atlas. Sem os dados do INMET, essas colunas ficam
    vazias — e vazio é honesto, diferente de preencher com zero, que o modelo
    leria como "não choveu".
    """
    features = atlas.features_para_consulta(
        ocorrencias, 3303906, "DESLIZAMENTO", ano=2026, mes=2
    )
    for coluna in esquema.COLUNAS_CLIMA:
        if coluna == "meses_de_clima_disponiveis":
            assert features[coluna] == 0
        else:
            assert np.isnan(features[coluna])


def test_consulta_usa_o_mesmo_calculo_do_treino(ocorrencias):
    """
    A consulta e o dataset de treino precisam produzir números idênticos para
    o mesmo mês. Se divergirem, o modelo é treinado com uma conta e usado com
    outra — o erro mais difícil de perceber num projeto de aprendizado.
    """
    dataset = atlas.construir_dataset(ocorrencias, 2015, 2025, 1, semente=7)

    linha = dataset[
        (dataset["codigo_ibge"] == 3303906)
        & (dataset["grupo_desastre"] == "DESLIZAMENTO")
    ].iloc[0]

    features = atlas.features_para_consulta(
        ocorrencias, 3303906, "DESLIZAMENTO",
        ano=int(linha["ano"]), mes=int(linha["mes"]),
    )

    # O clima entra depois, por outra fonte; aqui compara-se o que vem do Atlas.
    for coluna in esquema.COLUNAS_NUMERICAS:
        if coluna in esquema.COLUNAS_CLIMA:
            continue
        assert features[coluna] == pytest.approx(float(linha[coluna])), coluna


def test_consulta_de_municipio_sem_historico_nao_quebra(ocorrencias):
    features = atlas.features_para_consulta(
        ocorrencias, 3303906, "GRANIZO", ano=2026, mes=5
    )
    assert features["ocorrencias_total_historico"] == 0
    assert features["ja_ocorreu"] == 0
    assert features["meses_desde_ultima_ocorrencia"] == -1


# --------------------------------------------------------------------------
# Endpoints usados pela interface
# --------------------------------------------------------------------------


@precisa_de_dados
def test_busca_de_municipio_ignora_acento():
    com = cliente.get("/municipios", params={"busca": "Petrópolis"}).json()
    sem = cliente.get("/municipios", params={"busca": "petropolis"}).json()

    assert com["total"] > 0
    assert [m["codigo_ibge"] for m in com["municipios"]] == \
           [m["codigo_ibge"] for m in sem["municipios"]]


@precisa_de_dados
def test_busca_filtra_por_uf():
    dados = cliente.get("/municipios", params={"uf": "SC", "limite": 50}).json()
    assert dados["total"] > 0
    assert all(m["uf"] == "SC" for m in dados["municipios"])


@precisa_de_dados
def test_historico_de_municipio_inexistente_da_404():
    assert cliente.get("/municipios/9999999/historico").status_code == 404


@precisa_de_dados
def test_previsao_por_municipio_responde_completa():
    corpo = {"codigo_ibge": 3303906, "grupo_desastre": "DESLIZAMENTO",
             "mes": 2, "ano": 2026}
    resposta = cliente.post("/prever/municipio", json=corpo)
    assert resposta.status_code == 200, resposta.text

    dados = resposta.json()
    assert dados["nivel_risco"] in esquema.CLASSES_RISCO
    assert dados["cor"] == esquema.CORES_RISCO[dados["nivel_risco"]]
    assert set(dados["probabilidades"]) == set(esquema.CLASSES_RISCO)
    assert abs(sum(dados["probabilidades"].values()) - 1.0) < 0.01
    # A interface mostra estas variáveis na caixa "como o modelo chegou a isso".
    assert set(dados["historico_usado"]) == set(esquema.COLUNAS_NUMERICAS) - {"mes"}


@precisa_de_dados
def test_previsao_por_municipio_varia_com_o_mes():
    """Se o mês não mudasse nada, a sazonalidade não estaria sendo usada."""
    def risco(mes):
        corpo = {"codigo_ibge": 3303906, "grupo_desastre": "DESLIZAMENTO",
                 "mes": mes, "ano": 2026}
        return cliente.post("/prever/municipio", json=corpo).json()["probabilidades"]["alto"]

    # Em Petrópolis os deslizamentos se concentram no verão.
    assert risco(2) > risco(8)


@precisa_de_dados
def test_municipio_sem_historico_da_404():
    corpo = {"codigo_ibge": 9999999, "grupo_desastre": "INUNDACAO",
             "mes": 3, "ano": 2026}
    assert cliente.post("/prever/municipio", json=corpo).status_code == 404


@precisa_de_dados
def test_mes_invalido_na_consulta_e_rejeitado():
    corpo = {"codigo_ibge": 3303906, "grupo_desastre": "DESLIZAMENTO",
             "mes": 13, "ano": 2026}
    assert cliente.post("/prever/municipio", json=corpo).status_code == 422


# --------------------------------------------------------------------------
# Interface estática
# --------------------------------------------------------------------------


def test_interface_web_e_servida():
    resposta = cliente.get("/app/")
    assert resposta.status_code == 200
    assert "Previsão de Risco" in resposta.text


def test_arquivos_da_interface_existem():
    for arquivo in ("estilo.css", "app.js"):
        assert cliente.get(f"/app/{arquivo}").status_code == 200
