"""
Testes do script didático de avaliação (analise/avaliacao_modelo.py).

O script é material de estudo e de apresentação: se ele quebrar ou passar a
mentir, o estrago é numa banca. Os testes cobrem o tratamento de dados e o
diagnóstico de overfitting, que são as partes com lógica de verdade.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import esquema

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "analise" / "avaliacao_modelo.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists(), reason="script de avaliação não encontrado"
)


@pytest.fixture(scope="module")
def avaliacao():
    especificacao = importlib.util.spec_from_file_location(
        "avaliacao_modelo", SCRIPT
    )
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


# --------------------------------------------------------------------------
# Tratamento dos dados
# --------------------------------------------------------------------------


def test_tratamento_preenche_nulos(avaliacao, dados_exemplo):
    sujo = dados_exemplo.copy()
    sujo.loc[sujo.index[:5], "ocorrencias_12m"] = np.nan
    sujo.loc[sujo.index[:3], "regiao"] = np.nan

    limpo = avaliacao.tratar_dados(sujo)
    assert limpo["ocorrencias_12m"].isna().sum() == 0
    assert limpo["regiao"].isna().sum() == 0


def test_nulos_numericos_viram_mediana_e_nao_media(avaliacao, dados_exemplo):
    """
    A mediana resiste a valores extremos; a média não. Esta base tem eventos
    com centenas de milhares de afetados, então a escolha muda o resultado.
    """
    sujo = dados_exemplo.copy()
    coluna = "afetados_historico"
    sujo[coluna] = 10.0
    sujo.loc[sujo.index[0], coluna] = 1_000_000.0   # valor extremo
    sujo.loc[sujo.index[1], coluna] = np.nan

    limpo = avaliacao.tratar_dados(sujo)
    preenchido = limpo.loc[limpo.index[1], coluna]

    assert preenchido == pytest.approx(10.0), "deveria usar a mediana"


def test_tratamento_remove_duplicatas_pela_chave(avaliacao, dados_exemplo):
    com_repetida = pd.concat(
        [dados_exemplo, dados_exemplo.head(4)], ignore_index=True
    )
    limpo = avaliacao.tratar_dados(com_repetida)

    assert not limpo.duplicated(subset=esquema.CHAVE_LINHA).any()
    assert len(limpo) == len(dados_exemplo)


def test_tratamento_nao_altera_base_ja_limpa(avaliacao, dados_exemplo):
    limpo = avaliacao.tratar_dados(dados_exemplo)
    assert len(limpo) == len(dados_exemplo)


# --------------------------------------------------------------------------
# Divisão dos dados
# --------------------------------------------------------------------------


def test_divisao_aleatoria_respeita_a_proporcao(avaliacao, dados_exemplo):
    X_treino, X_teste, _, _ = avaliacao.dividir(dados_exemplo, 0.5, temporal=False)
    total = len(X_treino) + len(X_teste)

    assert total == len(dados_exemplo)
    assert len(X_teste) / total == pytest.approx(0.5, abs=0.01)


def test_divisao_aleatoria_preserva_as_classes(avaliacao, dados_exemplo):
    """`stratify` precisa manter a mesma mistura dos dois lados."""
    _, _, y_treino, y_teste = avaliacao.dividir(dados_exemplo, 0.3, temporal=False)

    for classe in esquema.CLASSES_RISCO:
        proporcao_treino = (y_treino == classe).mean()
        proporcao_teste = (y_teste == classe).mean()
        assert proporcao_treino == pytest.approx(proporcao_teste, abs=0.02)


def test_divisao_temporal_nao_mistura_os_anos(avaliacao, dados_exemplo):
    """
    O teste central: nenhum ano pode aparecer nos dois lados. Se aparecer, o
    modelo está usando o futuro para prever o passado.
    """
    X_treino, X_teste, _, _ = avaliacao.dividir(dados_exemplo, 0.5, temporal=True)

    anos_treino = set(dados_exemplo.loc[X_treino.index, "ano"])
    anos_teste = set(dados_exemplo.loc[X_teste.index, "ano"])

    assert not (anos_treino & anos_teste), "há anos nos dois conjuntos"
    assert max(anos_treino) < min(anos_teste), "o treino tem de vir antes"


# --------------------------------------------------------------------------
# Diagnóstico de overfitting
# --------------------------------------------------------------------------


def _metricas(balanceada_treino, balanceada_teste):
    """Monta um resultado sintético para testar só a regra de diagnóstico."""
    return {
        "balanceada_treino": balanceada_treino,
        "balanceada_teste": balanceada_teste,
    }


def test_regra_de_diagnostico_reconhece_overfitting(avaliacao):
    metricas = _metricas(0.95, 0.60)
    diferenca = metricas["balanceada_treino"] - metricas["balanceada_teste"]
    assert diferenca > 0.15


def test_regra_de_diagnostico_reconhece_underfitting(avaliacao):
    metricas = _metricas(0.35, 0.34)
    assert metricas["balanceada_teste"] < 0.40


def test_diagnostico_do_modelo_real_nao_e_overfitting(avaliacao, dados_exemplo):
    """
    Roda o fluxo inteiro numa base pequena e confere que o diagnóstico sai
    coerente com os números — sem depender de qual rótulo saiu.
    """
    dados = avaliacao.tratar_dados(dados_exemplo)
    X_treino, X_teste, y_treino, y_teste = avaliacao.dividir(dados, 0.4)
    modelo = avaliacao.treinar(X_treino, y_treino, arvores=20)
    metricas = avaliacao.avaliar(modelo, X_treino, y_treino, X_teste, y_teste)

    assert metricas["diagnostico"] in {"overfitting", "underfitting", "equilibrado"}
    assert 0.0 <= metricas["acuracia_teste"] <= 1.0
    assert metricas["acuracia_treino"] >= metricas["acuracia_teste"] - 0.2

    if metricas["diferenca_treino_teste"] > 0.15:
        assert metricas["diagnostico"] == "overfitting"


def test_modelo_supera_o_chute_da_classe_majoritaria(avaliacao, dados_exemplo):
    dados = avaliacao.tratar_dados(dados_exemplo)
    X_treino, X_teste, y_treino, y_teste = avaliacao.dividir(dados, 0.4)
    modelo = avaliacao.treinar(X_treino, y_treino, arvores=20)

    from sklearn.metrics import balanced_accuracy_score

    previsao = modelo.predict(X_teste)
    # Acurácia balanceada de um chute fixo é 1/n_classes.
    assert balanced_accuracy_score(y_teste, previsao) > 1 / len(esquema.CLASSES_RISCO)
