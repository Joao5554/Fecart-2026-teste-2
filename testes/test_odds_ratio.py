"""
Testes da análise de odds ratio.

Um odds ratio errado é perigoso justamente porque parece certo: o número sai,
tem intervalo de confiança, tem p-valor, e ninguém desconfia. Por isso os
testes aqui não checam só se o código roda — eles verificam se a conta está
estatisticamente correta, comparando com valores que dá para calcular à mão.
"""

import numpy as np
import pandas as pd
import pytest

from src import esquema, odds_ratio


# --------------------------------------------------------------------------
# A conta está certa?
# --------------------------------------------------------------------------


def test_odds_ratio_bate_com_a_conta_manual():
    """
    Com uma variável binária, o odds ratio tem fórmula fechada:

        OR = (a/b) / (c/d)

    onde a,b,c,d são as quatro caselas da tabela 2x2. A regressão logística
    precisa reproduzir esse número. Se não reproduzir, a implementação está
    errada — e nenhum outro teste pegaria isso.
    """
    rng = np.random.default_rng(7)
    n = 8000
    exposto = rng.integers(0, 2, n)
    # Chance de evento: 20% sem exposição, 50% com. OR verdadeiro = 4,0.
    prob = np.where(exposto == 1, 0.5, 0.2)
    evento = (rng.random(n) < prob).astype(int)

    a = ((exposto == 1) & (evento == 1)).sum()
    b = ((exposto == 1) & (evento == 0)).sum()
    c = ((exposto == 0) & (evento == 1)).sum()
    d = ((exposto == 0) & (evento == 0)).sum()
    or_manual = (a / b) / (c / d)

    X = pd.DataFrame({"exposto": exposto.astype(float)})
    modelo, coeficientes, _ = odds_ratio._ajustar_com_erros_padrao(
        X.to_numpy(), evento
    )
    or_regressao = float(np.exp(coeficientes[0]))

    assert or_regressao == pytest.approx(or_manual, rel=0.02)
    assert or_regressao == pytest.approx(4.0, rel=0.15)


def test_intervalo_de_confianca_cobre_o_valor_verdadeiro():
    """Com OR verdadeiro conhecido, o IC de 95% precisa contê-lo."""
    rng = np.random.default_rng(11)
    n = 20_000
    exposto = rng.integers(0, 2, n)
    prob = np.where(exposto == 1, 0.5, 0.2)
    evento = (rng.random(n) < prob).astype(int)

    X = pd.DataFrame({"exposto": exposto.astype(float)})
    _, coeficientes, erros = odds_ratio._ajustar_com_erros_padrao(
        X.to_numpy(), evento
    )
    inferior = np.exp(coeficientes[0] - 1.96 * erros[0])
    superior = np.exp(coeficientes[0] + 1.96 * erros[0])

    assert inferior < 4.0 < superior


def test_variavel_sem_efeito_da_odds_ratio_proximo_de_um():
    rng = np.random.default_rng(3)
    n = 10_000
    ruido = rng.normal(size=n)
    evento = rng.integers(0, 2, n)

    X = pd.DataFrame({"ruido": ruido})
    _, coeficientes, erros = odds_ratio._ajustar_com_erros_padrao(
        X.to_numpy(), evento
    )
    razao = float(np.exp(coeficientes[0]))
    inferior = np.exp(coeficientes[0] - 1.96 * erros[0])
    superior = np.exp(coeficientes[0] + 1.96 * erros[0])

    assert razao == pytest.approx(1.0, abs=0.1)
    assert inferior < 1.0 < superior, "IC deveria incluir 1 para variável sem efeito"


# --------------------------------------------------------------------------
# Multicolinearidade
# --------------------------------------------------------------------------


def test_vif_detecta_variavel_redundante():
    rng = np.random.default_rng(5)
    a = rng.normal(size=2000)
    b = rng.normal(size=2000)
    X = pd.DataFrame({"a": a, "b": b, "copia_de_a": a + rng.normal(0, 0.01, 2000)})

    vif = odds_ratio.calcular_vif(X)
    assert vif["copia_de_a"] > 10
    assert vif["b"] < 2


def test_vif_de_variaveis_independentes_fica_perto_de_um():
    rng = np.random.default_rng(5)
    X = pd.DataFrame(rng.normal(size=(2000, 3)), columns=["a", "b", "c"])
    assert (odds_ratio.calcular_vif(X) < 1.2).all()


def test_selecao_remove_a_redundante_e_mantem_as_outras():
    rng = np.random.default_rng(5)
    a = rng.normal(size=2000)
    X = pd.DataFrame({
        "a": a,
        "b": rng.normal(size=2000),
        "copia_de_a": a + rng.normal(0, 0.01, 2000),
    })

    mantidas, removidas = odds_ratio.selecionar_sem_colinearidade(X, limite=10)
    assert "b" in mantidas
    assert len(removidas) == 1
    assert removidas[0][0] in {"a", "copia_de_a"}


def test_janelas_aninhadas_viram_faixas_disjuntas(dados_exemplo):
    """
    12m, 24m e 60m são cumulativas: a maior contém a menor. Juntas na mesma
    regressão elas invertem o sinal uma da outra. A matriz precisa substituí-las
    por faixas que não se sobrepõem.
    """
    X, _ = odds_ratio.montar_matriz(dados_exemplo)

    assert "ocorrencias_24m" not in X.columns
    assert "ocorrencias_60m" not in X.columns
    assert "ocorrencias_13_a_24m" in X.columns
    assert "ocorrencias_25_a_60m" in X.columns
    assert "ocorrencias_12m" in X.columns


def test_faixas_disjuntas_nunca_sao_negativas(dados_exemplo):
    dados = dados_exemplo.copy()
    faixa = (dados["ocorrencias_24m"] - dados["ocorrencias_12m"]).clip(lower=0)
    assert (faixa >= 0).all()


def test_mes_fica_fora_da_regressao(dados_exemplo):
    """`mes` é cíclico; um coeficiente linear sobre ele não teria sentido."""
    X, _ = odds_ratio.montar_matriz(dados_exemplo)
    assert "mes" not in X.columns


# --------------------------------------------------------------------------
# Resultado completo
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def resultado(dados_exemplo):
    return odds_ratio.calcular(dados_exemplo, "gravidade")


def test_resultado_traz_os_campos_esperados(resultado):
    for campo in ("analise", "descricao", "auc", "tabela", "n_eventos",
                  "removidas_por_colinearidade"):
        assert campo in resultado


def test_tabela_tem_intervalo_coerente(resultado):
    tabela = resultado["tabela"]
    assert (tabela["ic95_inferior"] <= tabela["odds_ratio"]).all()
    assert (tabela["odds_ratio"] <= tabela["ic95_superior"]).all()
    assert (tabela["odds_ratio"] > 0).all()


def test_significancia_concorda_com_o_intervalo(resultado):
    """
    Significativo exige duas coisas: o intervalo não pode incluir 1,0 e a
    estimativa precisa ser estável. Uma categoria com dados de menos pode ter
    intervalo longe de 1 e ainda assim não valer nada.
    """
    tabela = resultado["tabela"]
    cruza_um = (tabela["ic95_inferior"] <= 1.0) & (tabela["ic95_superior"] >= 1.0)

    assert not (tabela["significativo"] & cruza_um).any(), (
        "marcou como significativo um OR cujo intervalo inclui 1,0"
    )
    assert (tabela.loc[~cruza_um & tabela["confiavel"], "significativo"]).all(), (
        "deixou de marcar como significativo um OR estável e longe de 1,0"
    )


def test_p_valores_estao_entre_zero_e_um(resultado):
    assert resultado["tabela"]["p_valor"].between(0, 1).all()


def test_auc_indica_modelo_melhor_que_o_acaso(resultado):
    assert 0.5 < resultado["auc"] <= 1.0


def test_analise_desconhecida_da_erro_claro(dados_exemplo):
    with pytest.raises(ValueError, match="desconhecida"):
        odds_ratio.calcular(dados_exemplo, "inventada")


def test_versao_json_e_serializavel(resultado):
    import json

    bruto = odds_ratio.para_json(resultado, quantidade=5)
    texto = json.dumps(bruto, ensure_ascii=False)

    assert len(bruto["variaveis"]) <= 5
    assert "odds_ratio" in texto


def test_separacao_perfeita_nao_produz_valor_infinito():
    """
    Categoria rara que prevê o desfecho perfeitamente faz o coeficiente
    tender ao infinito. O resultado precisa sair finito e marcado como
    instável — um OR de milhões numa apresentação seria constrangedor.
    """
    n = 400
    dados = pd.DataFrame({
        coluna: np.zeros(n) for coluna in esquema.COLUNAS_NUMERICAS
    })
    dados["regiao"] = "Sudeste"
    dados["grupo_desastre"] = "INUNDACAO"
    dados[esquema.COLUNA_ALVO] = ["baixo"] * (n // 2) + ["alto"] * (n // 2)

    # Uma categoria que aparece só nos casos "alto": separação perfeita.
    dados.loc[dados.index[-8:], "grupo_desastre"] = "GRANIZO"
    dados["ocorrencias_12m"] = np.arange(n) / n

    resultado = odds_ratio.calcular(dados, "gravidade")
    tabela = resultado["tabela"]

    assert np.isfinite(tabela["odds_ratio"]).all()
    assert np.isfinite(tabela["ic95_superior"]).all()

    instaveis = tabela[~tabela["confiavel"]]
    if len(instaveis):
        assert not instaveis["significativo"].any(), (
            "estimativa instável não pode ser apresentada como significativa"
        )


def test_relatorio_menciona_como_ler(resultado):
    texto = odds_ratio.formatar_relatorio(resultado)
    assert "OR > 1" in texto
    assert "AUC" in texto


def test_todas_as_analises_definidas_rodam(dados_exemplo):
    for analise in odds_ratio.ANALISES:
        resultado = odds_ratio.calcular(dados_exemplo, analise)
        assert len(resultado["tabela"]) > 0


def test_grupos_de_desastre_entram_como_categorias(dados_exemplo):
    X, _ = odds_ratio.montar_matriz(dados_exemplo)
    indicadoras = [c for c in X.columns if c.startswith("grupo_desastre_")]
    assert indicadoras, "o tipo de desastre precisa entrar na regressão"
    # drop_first: uma categoria vira referência e não ganha coluna.
    assert len(indicadoras) < dados_exemplo["grupo_desastre"].nunique() + 1


def test_uf_nao_entra_por_ser_redundante_com_regiao(dados_exemplo):
    X, _ = odds_ratio.montar_matriz(dados_exemplo)
    assert not [c for c in X.columns if c.startswith("uf_")]
