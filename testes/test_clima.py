"""
Testes das variáveis climáticas.

O teste mais importante deste arquivo é o de vazamento: a chuva usada para
prever um mês precisa ser a dos meses ANTERIORES. Se a chuva do próprio mês
entrasse, o modelo pareceria excelente e não serviria para nada — em janeiro,
a chuva de fevereiro ainda não aconteceu.
"""

import numpy as np
import pandas as pd
import pytest

from src import clima


@pytest.fixture
def clima_mensal():
    """Um município com chuva conhecida e crescente, mês a mês."""
    linhas = []
    for mes in range(1, 13):
        linhas.append({
            "codigo_ibge": 3303906, "ano": 2020, "mes": mes,
            "chuva_total_mm": mes * 10.0,          # jan=10, fev=20, ...
            "chuva_max_dia_mm": mes * 2.0,
            "dias_com_chuva": mes,
            "temperatura_media_c": 20.0 + mes,
            "umidade_media_pct": 70.0,
            "rajada_max_kmh": 30.0 + mes,
            "fonte_clima": "municipio",
        })
    return pd.DataFrame(linhas)


@pytest.fixture
def alvos():
    return pd.DataFrame([
        {"codigo_ibge": 3303906, "ano": 2020, "mes": mes} for mes in range(1, 13)
    ])


# --------------------------------------------------------------------------
# Vazamento temporal
# --------------------------------------------------------------------------


def test_usa_a_chuva_do_mes_anterior_e_nao_a_do_proprio_mes(alvos, clima_mensal):
    """
    O teste central. Para o alvo de março (mês 3), a chuva precisa ser a de
    fevereiro (20 mm), nunca a de março (30 mm).
    """
    resultado = clima.adicionar_features(alvos, clima_mensal)
    marco = resultado[resultado["mes"] == 3].iloc[0]

    assert marco["chuva_mes_anterior_mm"] == pytest.approx(20.0)
    assert marco["chuva_mes_anterior_mm"] != pytest.approx(30.0), "usou o próprio mês"


def test_todas_as_linhas_usam_o_mes_anterior(alvos, clima_mensal):
    resultado = clima.adicionar_features(alvos, clima_mensal).sort_values("mes")

    for _, linha in resultado.iterrows():
        if linha["mes"] == 1:
            # Janeiro não tem mês anterior dentro do período fornecido.
            assert pd.isna(linha["chuva_mes_anterior_mm"])
        else:
            esperado = (linha["mes"] - 1) * 10.0
            assert linha["chuva_mes_anterior_mm"] == pytest.approx(esperado)


def test_acumulado_de_tres_meses_soma_os_anteriores(alvos, clima_mensal):
    """Para maio (mês 5): fevereiro + março + abril = 20 + 30 + 40 = 90."""
    resultado = clima.adicionar_features(alvos, clima_mensal)
    maio = resultado[resultado["mes"] == 5].iloc[0]

    assert maio["chuva_3_meses_anteriores_mm"] == pytest.approx(90.0)
    assert maio["meses_de_clima_disponiveis"] == 3


def test_conta_quantos_meses_de_clima_existem(alvos, clima_mensal):
    """Fevereiro só tem janeiro atrás dele dentro do período."""
    resultado = clima.adicionar_features(alvos, clima_mensal)
    fevereiro = resultado[resultado["mes"] == 2].iloc[0]

    assert fevereiro["meses_de_clima_disponiveis"] == 1
    assert fevereiro["chuva_3_meses_anteriores_mm"] == pytest.approx(10.0)


def test_demais_variaveis_tambem_vem_do_mes_anterior(alvos, clima_mensal):
    resultado = clima.adicionar_features(alvos, clima_mensal)
    junho = resultado[resultado["mes"] == 6].iloc[0]

    assert junho["temperatura_mes_anterior_c"] == pytest.approx(25.0)   # maio
    assert junho["rajada_mes_anterior_kmh"] == pytest.approx(35.0)      # maio
    assert junho["dias_com_chuva_mes_anterior"] == 5                    # maio


# --------------------------------------------------------------------------
# Normal climatológica e anomalia
# --------------------------------------------------------------------------


def test_normal_usa_so_o_periodo_de_referencia():
    linhas = [
        {"codigo_ibge": 1, "ano": ano, "mes": 3, "chuva_total_mm": chuva}
        for ano, chuva in [(2005, 100.0), (2008, 200.0), (2015, 900.0)]
    ]
    normais = clima.calcular_normais_municipais(pd.DataFrame(linhas), 2000, 2009)

    assert len(normais) == 1
    assert normais["chuva_normal_mm"].iloc[0] == pytest.approx(150.0)
    assert normais["anos_na_normal"].iloc[0] == 2


def test_anomalia_positiva_quando_chove_acima_do_normal():
    """Chuva do dobro da normal = anomalia de +100%."""
    normais = pd.DataFrame([
        {"codigo_ibge": 1, "mes": 1, "chuva_normal_mm": 100.0, "anos_na_normal": 10}
    ])
    clima_mensal = pd.DataFrame([{
        "codigo_ibge": 1, "ano": 2020, "mes": 1, "chuva_total_mm": 200.0,
        "chuva_max_dia_mm": 50.0, "dias_com_chuva": 15,
        "temperatura_media_c": 25.0, "umidade_media_pct": 80.0,
        "rajada_max_kmh": 40.0,
    }])
    alvos = pd.DataFrame([{"codigo_ibge": 1, "ano": 2020, "mes": 2}])

    resultado = clima.adicionar_features(alvos, clima_mensal, normais)
    assert resultado["anomalia_chuva_pct"].iloc[0] == pytest.approx(100.0)


def test_anomalia_negativa_quando_chove_abaixo_do_normal():
    normais = pd.DataFrame([
        {"codigo_ibge": 1, "mes": 1, "chuva_normal_mm": 100.0, "anos_na_normal": 10}
    ])
    clima_mensal = pd.DataFrame([{
        "codigo_ibge": 1, "ano": 2020, "mes": 1, "chuva_total_mm": 25.0,
        "chuva_max_dia_mm": 5.0, "dias_com_chuva": 2,
        "temperatura_media_c": 25.0, "umidade_media_pct": 60.0,
        "rajada_max_kmh": 30.0,
    }])
    alvos = pd.DataFrame([{"codigo_ibge": 1, "ano": 2020, "mes": 2}])

    resultado = clima.adicionar_features(alvos, clima_mensal, normais)
    assert resultado["anomalia_chuva_pct"].iloc[0] == pytest.approx(-75.0)


def test_anomalia_de_janeiro_compara_com_dezembro():
    """O mês anterior a janeiro é dezembro; a normal precisa ser a de dezembro."""
    normais = pd.DataFrame([
        {"codigo_ibge": 1, "mes": 12, "chuva_normal_mm": 50.0, "anos_na_normal": 10},
        {"codigo_ibge": 1, "mes": 1, "chuva_normal_mm": 500.0, "anos_na_normal": 10},
    ])
    clima_mensal = pd.DataFrame([{
        "codigo_ibge": 1, "ano": 2019, "mes": 12, "chuva_total_mm": 100.0,
        "chuva_max_dia_mm": 20.0, "dias_com_chuva": 8,
        "temperatura_media_c": 25.0, "umidade_media_pct": 80.0,
        "rajada_max_kmh": 40.0,
    }])
    alvos = pd.DataFrame([{"codigo_ibge": 1, "ano": 2020, "mes": 1}])

    resultado = clima.adicionar_features(alvos, clima_mensal, normais)
    # 100 contra normal de dezembro (50) = +100%. Se usasse a de janeiro (500),
    # daria -80%.
    assert resultado["anomalia_chuva_pct"].iloc[0] == pytest.approx(100.0)


def test_anomalia_e_limitada_para_nao_explodir():
    """Normal minúscula (mês seco no sertão) geraria anomalia de milhares por cento."""
    normais = pd.DataFrame([
        {"codigo_ibge": 1, "mes": 1, "chuva_normal_mm": 0.5, "anos_na_normal": 10}
    ])
    clima_mensal = pd.DataFrame([{
        "codigo_ibge": 1, "ano": 2020, "mes": 1, "chuva_total_mm": 200.0,
        "chuva_max_dia_mm": 50.0, "dias_com_chuva": 10,
        "temperatura_media_c": 30.0, "umidade_media_pct": 50.0,
        "rajada_max_kmh": 40.0,
    }])
    alvos = pd.DataFrame([{"codigo_ibge": 1, "ano": 2020, "mes": 2}])

    resultado = clima.adicionar_features(alvos, clima_mensal, normais)
    assert resultado["anomalia_chuva_pct"].iloc[0] == pytest.approx(500.0)


def test_sem_normal_a_anomalia_fica_nula(alvos, clima_mensal):
    vazia = pd.DataFrame(columns=["codigo_ibge", "mes", "chuva_normal_mm"])
    resultado = clima.adicionar_features(alvos, clima_mensal, vazia)

    assert resultado["anomalia_chuva_pct"].isna().all()


# --------------------------------------------------------------------------
# Casos sem dado
# --------------------------------------------------------------------------


def test_municipio_sem_clima_fica_com_nulo(clima_mensal):
    alvos = pd.DataFrame([{"codigo_ibge": 9999999, "ano": 2020, "mes": 5}])
    resultado = clima.adicionar_features(alvos, clima_mensal)

    assert pd.isna(resultado["chuva_mes_anterior_mm"].iloc[0])
    assert resultado["meses_de_clima_disponiveis"].iloc[0] == 0


def test_nao_perde_nem_duplica_linhas(alvos, clima_mensal):
    resultado = clima.adicionar_features(alvos, clima_mensal)
    assert len(resultado) == len(alvos)


def test_todas_as_colunas_declaradas_sao_criadas(alvos, clima_mensal):
    resultado = clima.adicionar_features(alvos, clima_mensal)
    for coluna in clima.COLUNAS_CLIMA:
        assert coluna in resultado.columns


def test_resumo_de_cobertura_conta_certo(alvos, clima_mensal):
    resultado = clima.adicionar_features(alvos, clima_mensal)
    cobertura = clima.resumir_cobertura(resultado)

    assert cobertura["linhas"] == 12
    # Janeiro não tem mês anterior; os outros 11 têm.
    assert cobertura["com_chuva_do_mes_anterior"] == 11
