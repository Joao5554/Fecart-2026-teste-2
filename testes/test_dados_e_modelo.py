"""
Testes do gerador de dados e do treinamento.

Usam poucas amostras para rodar rápido: o objetivo é verificar que o
pipeline funciona e é reprodutível, não medir a qualidade final do modelo.
"""

import pandas as pd
import pytest
from sklearn.model_selection import train_test_split

from treinamento.esquema import COLUNA_ALVO, COLUNAS_NUMERICAS, NOMES_COLUNAS
from treinamento.gerar_dados_exemplo import gerar
from treinamento.preprocessamento import (
    DadosInvalidosError,
    separar_x_y,
    validar_dados,
)
from treinamento.treinar_modelo import criar_modelo, importancia_variaveis


@pytest.fixture(scope="module")
def dados():
    return gerar(n_amostras=600, semente=7)


def test_dados_seguem_o_esquema(dados):
    assert list(dados.columns) == list(NOMES_COLUNAS) + [COLUNA_ALVO]
    validar_dados(dados, exigir_alvo=True)


def test_geracao_e_reprodutivel():
    """Mesma semente precisa gerar exatamente o mesmo conjunto de dados."""
    primeiro = gerar(n_amostras=200, semente=123)
    segundo = gerar(n_amostras=200, semente=123)
    pd.testing.assert_frame_equal(primeiro, segundo)


def test_sementes_diferentes_geram_dados_diferentes():
    primeiro = gerar(n_amostras=200, semente=1)
    segundo = gerar(n_amostras=200, semente=2)
    assert not primeiro.equals(segundo)


def test_dados_sem_valores_faltantes(dados):
    assert not dados.isna().any().any()


def test_valores_numericos_dentro_da_faixa(dados):
    from treinamento.esquema import COLUNAS_POR_NOME

    for nome in COLUNAS_NUMERICAS:
        coluna = COLUNAS_POR_NOME[nome]
        assert dados[nome].min() >= coluna.minimo, nome
        assert dados[nome].max() <= coluna.maximo, nome


def test_todas_as_classes_aparecem(dados):
    from treinamento.esquema import CLASSES

    assert set(dados[COLUNA_ALVO].unique()) == set(CLASSES)


def test_validacao_reclama_de_coluna_faltando(dados):
    incompletos = dados.drop(columns=["precipitacao_mm"])
    with pytest.raises(DadosInvalidosError, match="precipitacao_mm"):
        validar_dados(incompletos, exigir_alvo=True)


def test_validacao_reclama_de_coluna_numerica_com_texto(dados):
    quebrados = dados.copy()
    quebrados["precipitacao_mm"] = "muita chuva"
    with pytest.raises(DadosInvalidosError, match="numérica"):
        validar_dados(quebrados, exigir_alvo=True)


def test_validacao_reclama_de_base_vazia(dados):
    with pytest.raises(DadosInvalidosError, match="vazio"):
        validar_dados(dados.iloc[0:0], exigir_alvo=True)


@pytest.fixture(scope="module")
def modelo_treinado(dados):
    X, y = separar_x_y(dados)
    X_treino, _, y_treino, _ = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    modelo = criar_modelo()
    modelo.fit(X_treino, y_treino)
    return modelo


def test_modelo_treina_e_preve(modelo_treinado, dados):
    X, _ = separar_x_y(dados)
    previsoes = modelo_treinado.predict(X.head(10))
    assert len(previsoes) == 10


def test_probabilidades_somam_um(modelo_treinado, dados):
    X, _ = separar_x_y(dados)
    probabilidades = modelo_treinado.predict_proba(X.head(20))
    assert probabilidades.shape[1] == len(modelo_treinado.classes_)
    for linha in probabilidades:
        assert abs(linha.sum() - 1.0) < 1e-6


def test_modelo_aprende_melhor_que_o_acaso(modelo_treinado, dados):
    """Sanidade: precisa superar com folga o chute da classe majoritária."""
    from sklearn.metrics import accuracy_score

    X, y = separar_x_y(dados)
    acuracia = accuracy_score(y, modelo_treinado.predict(X))
    maioria = y.value_counts(normalize=True).max()
    assert acuracia > maioria


def test_importancia_cobre_todas_as_variaveis(modelo_treinado):
    importancias = importancia_variaveis(modelo_treinado)
    assert set(importancias) == set(NOMES_COLUNAS)
    assert abs(sum(importancias.values()) - 1.0) < 1e-6


def test_modelo_aceita_categoria_desconhecida(modelo_treinado, dados):
    """A API não pode quebrar se chegar uma UF que não apareceu no treino."""
    X, _ = separar_x_y(dados)
    entrada = X.head(1).copy()
    entrada.loc[entrada.index[0], "uf"] = "ZZ"
    assert len(modelo_treinado.predict(entrada)) == 1
