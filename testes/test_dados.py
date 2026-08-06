"""
Testes do contrato de dados, das features derivadas e da validação.

Rodar:  pytest testes/ -v
"""

import numpy as np
import pandas as pd
import pytest

from src import caracteristicas, esquema
from src.carregar import ErroDeDados, carregar_dados, validar


# --------------------------------------------------------------------------
# Contrato (src/esquema.py)
# --------------------------------------------------------------------------


def test_nao_ha_nomes_de_coluna_repetidos():
    """Nome repetido entre grupos faria a coluna entrar duas vezes no modelo."""
    todos = (
        esquema.COLUNAS_IDENTIFICACAO
        + esquema.COLUNAS_CATEGORICAS
        + esquema.COLUNAS_NUMERICAS
        + esquema.COLUNAS_DERIVADAS
    )
    repetidos = [n for n in set(todos) if todos.count(n) > 1]
    assert not repetidos, f"colunas duplicadas no esquema: {repetidos}"


def test_indice_por_nome_cobre_todas_as_colunas():
    for nome in esquema.COLUNAS_NUMERICAS + esquema.COLUNAS_CATEGORICAS:
        assert nome in esquema.POR_NOME


def test_toda_classe_de_risco_tem_cor_no_mapa():
    for classe in esquema.CLASSES_RISCO:
        assert classe in esquema.CORES_RISCO


def test_faixas_numericas_sao_coerentes():
    for coluna in esquema.NUMERICAS:
        if coluna.minimo is not None and coluna.maximo is not None:
            assert coluna.minimo < coluna.maximo, f"faixa inválida em {coluna.nome}"


# --------------------------------------------------------------------------
# Dados gerados
# --------------------------------------------------------------------------


def test_dados_gerados_seguem_o_contrato(dados_exemplo):
    assert list(dados_exemplo.columns) == list(esquema.COLUNAS_OBRIGATORIAS)
    assert len(dados_exemplo) > 0


def test_dados_gerados_passam_na_validacao(dados_exemplo):
    relatorio = validar(dados_exemplo)
    assert relatorio.valido, f"erros inesperados: {relatorio.erros}"


def test_dados_gerados_tem_as_tres_classes(dados_exemplo):
    presentes = set(dados_exemplo[esquema.COLUNA_ALVO].unique())
    assert presentes == set(esquema.CLASSES_RISCO)


def test_geracao_e_reproduzivel():
    """Mesma semente, mesmo resultado — senão o treino não é reproduzível."""
    from gerar_dados_sinteticos import gerar

    a = gerar(2022, 2022, semente=1)
    b = gerar(2022, 2022, semente=1)
    pd.testing.assert_frame_equal(a, b)


# --------------------------------------------------------------------------
# Features derivadas
# --------------------------------------------------------------------------


def test_derivadas_sao_todas_criadas(dados_exemplo):
    resultado = caracteristicas.adicionar_derivadas(dados_exemplo)
    for nome in esquema.COLUNAS_DERIVADAS:
        assert nome in resultado.columns


def test_mes_ciclico_aproxima_dezembro_de_janeiro():
    """Dezembro e janeiro devem ficar perto; junho, longe dos dois."""
    base = pd.DataFrame({
        "mes": [12, 1, 6],
        "chuva_acumulada_mm": [100.0] * 3,
        "chuva_max_24h_mm": [30.0] * 3,
        "dias_com_chuva": [10] * 3,
        "meses_desde_ultima_ocorrencia": [5] * 3,
    })
    r = caracteristicas.adicionar_derivadas(base)
    pontos = list(zip(r["mes_seno"], r["mes_cosseno"]))

    distancia = lambda a, b: np.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731
    assert distancia(pontos[0], pontos[1]) < distancia(pontos[0], pontos[2])


def test_intensidade_de_chuva_nao_estoura_com_chuva_zero():
    """Mês sem chuva não pode virar divisão por zero (NaN quebra o treino)."""
    base = pd.DataFrame({
        "mes": [7],
        "chuva_acumulada_mm": [0.0],
        "chuva_max_24h_mm": [0.0],
        "dias_com_chuva": [0],
        "meses_desde_ultima_ocorrencia": [999],
    })
    r = caracteristicas.adicionar_derivadas(base)

    assert r["intensidade_chuva"].iloc[0] == 0.0
    assert r["chuva_por_dia_chuvoso"].iloc[0] == 0.0
    assert not r[esquema.COLUNAS_DERIVADAS].isna().any().any()


def test_ja_ocorreu_distingue_nunca_ocorrido():
    base = pd.DataFrame({
        "mes": [3, 3],
        "chuva_acumulada_mm": [100.0, 100.0],
        "chuva_max_24h_mm": [20.0, 20.0],
        "dias_com_chuva": [8, 8],
        "meses_desde_ultima_ocorrencia": [999, 4],
    })
    r = caracteristicas.adicionar_derivadas(base)
    assert r["ja_ocorreu"].tolist() == [0.0, 1.0]


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------


def test_validacao_acusa_coluna_faltando(dados_exemplo):
    incompleto = dados_exemplo.drop(columns=["chuva_max_24h_mm"])
    relatorio = validar(incompleto)

    assert not relatorio.valido
    assert "chuva_max_24h_mm" in " ".join(relatorio.erros)


def test_validacao_acusa_nivel_de_risco_invalido(dados_exemplo):
    ruim = dados_exemplo.copy()
    ruim.loc[ruim.index[0], esquema.COLUNA_ALVO] = "altissimo"
    relatorio = validar(ruim)

    assert not relatorio.valido
    assert "altissimo" in " ".join(relatorio.erros)


def test_validacao_acusa_classe_ausente(dados_exemplo):
    """Sem exemplos de 'alto' o modelo nunca preveria risco alto."""
    sem_alto = dados_exemplo[dados_exemplo[esquema.COLUNA_ALVO] != "alto"]
    relatorio = validar(sem_alto)

    assert not relatorio.valido
    assert "alto" in " ".join(relatorio.erros)


def test_validacao_acusa_alvo_vazio(dados_exemplo):
    ruim = dados_exemplo.copy()
    ruim.loc[ruim.index[:3], esquema.COLUNA_ALVO] = np.nan
    relatorio = validar(ruim)

    assert not relatorio.valido


def test_validacao_avisa_valor_fora_da_faixa(dados_exemplo):
    estranho = dados_exemplo.copy()
    estranho.loc[estranho.index[0], "chuva_acumulada_mm"] = -50.0
    relatorio = validar(estranho)

    # Fora da faixa é aviso, não erro: pode ser um extremo real.
    assert relatorio.valido
    assert any("chuva_acumulada_mm" in a for a in relatorio.avisos)


def test_validacao_avisa_uf_desconhecida(dados_exemplo):
    estranho = dados_exemplo.copy()
    estranho.loc[estranho.index[0], "uf"] = "XX"
    relatorio = validar(estranho)

    assert any("uf" in a and "XX" in a for a in relatorio.avisos)


def test_validacao_sem_alvo_para_previsao(dados_exemplo):
    """Na hora de prever, o CSV não tem a coluna de risco — e isso é normal."""
    sem_alvo = dados_exemplo.drop(columns=[esquema.COLUNA_ALVO])
    relatorio = validar(sem_alvo, exigir_alvo=False)

    assert relatorio.valido


def test_validacao_rejeita_base_vazia(dados_exemplo):
    relatorio = validar(dados_exemplo.iloc[0:0])
    assert not relatorio.valido


def test_arquivo_inexistente_explica_o_que_fazer(tmp_path):
    with pytest.raises(ErroDeDados) as erro:
        carregar_dados(tmp_path / "nao_existe.csv")

    assert "gerar_dados_sinteticos" in str(erro.value)
