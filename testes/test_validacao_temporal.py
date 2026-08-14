"""
Testes da validação temporal.

Um erro aqui é invisível: o modelo continua treinando, as métricas continuam
saindo, e ninguém percebe que o futuro vazou para o treino. Os testes abaixo
verificam justamente as fronteiras entre os conjuntos.
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.tree import DecisionTreeClassifier

from src import esquema, validacao_temporal


@pytest.fixture
def base_anual():
    """Base pequena com anos de 2010 a 2025, para testar as divisões."""
    rng = np.random.default_rng(3)
    linhas = []
    for ano in range(2010, 2026):
        for _ in range(60):
            linhas.append({
                "ano": ano,
                "x1": rng.normal(),
                "x2": rng.normal(),
                esquema.COLUNA_ALVO: rng.choice(esquema.CLASSES_RISCO),
            })
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------
# Janelas
# --------------------------------------------------------------------------


def test_janelas_avancam_um_ano_por_vez(base_anual):
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"],
                                               anos_minimos_treino=8)
    for treino_ate, ano_teste in janelas:
        assert ano_teste == treino_ate + 1, "a janela precisa avançar um ano"


def test_janela_nunca_testa_no_passado(base_anual):
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"])
    for treino_ate, ano_teste in janelas:
        assert ano_teste > treino_ate, "estaria testando no passado do treino"


def test_respeita_o_minimo_de_anos_de_treino(base_anual):
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"],
                                               anos_minimos_treino=10)
    primeiro_ano = base_anual["ano"].min()
    for treino_ate, _ in janelas:
        assert treino_ate - primeiro_ano + 1 >= 10


def test_maximo_de_janelas_pega_as_mais_recentes(base_anual):
    todas = validacao_temporal.gerar_janelas(base_anual["ano"])
    limitadas = validacao_temporal.gerar_janelas(base_anual["ano"],
                                                 maximo_janelas=3)
    assert len(limitadas) == 3
    assert limitadas == todas[-3:]


def test_base_curta_demais_da_erro_claro():
    anos = pd.Series([2020, 2021, 2022])
    with pytest.raises(ValueError, match="anos"):
        validacao_temporal.gerar_janelas(anos, anos_minimos_treino=8)


# --------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------


def test_walk_forward_treina_so_com_o_passado(base_anual):
    """
    O teste central deste arquivo.

    O modelo espião registra quais anos viu no treino de cada janela. Nenhum
    deles pode ser igual ou posterior ao ano avaliado.
    """
    anos_vistos = []

    class Espiao(DummyClassifier):
        def fit(self, X, y):
            anos_vistos.append(set(X["ano_marcador"]))
            return super().fit(X, y)

    X = base_anual[["x1", "x2"]].copy()
    X["ano_marcador"] = base_anual["ano"]
    y = base_anual[esquema.COLUNA_ALVO]

    janelas = validacao_temporal.gerar_janelas(base_anual["ano"])
    validacao_temporal.validar_walk_forward(
        lambda: Espiao(strategy="most_frequent"),
        X, y, base_anual["ano"], janelas,
    )

    for (_, ano_teste), anos in zip(janelas, anos_vistos):
        assert max(anos) < ano_teste, (
            f"a janela que testa {ano_teste} treinou com o ano {max(anos)}"
        )


def test_walk_forward_resume_as_janelas(base_anual):
    X = base_anual[["x1", "x2"]]
    y = base_anual[esquema.COLUNA_ALVO]
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"])

    resumo = validacao_temporal.validar_walk_forward(
        lambda: DecisionTreeClassifier(max_depth=3, random_state=1),
        X, y, base_anual["ano"], janelas,
    )

    assert resumo["n_janelas"] == len(janelas)
    for chave in ("balanceada_media", "balanceada_desvio", "balanceada_pior"):
        assert chave in resumo
    assert resumo["balanceada_pior"] <= resumo["balanceada_media"]


def test_walk_forward_treina_modelo_novo_a_cada_janela(base_anual):
    """Reaproveitar o modelo carregaria o aprendizado de uma janela futura."""
    # As referências são guardadas de propósito: comparar id() de objetos já
    # coletados daria falso positivo, porque o Python reaproveita endereços.
    criados = []

    def criar():
        modelo = DecisionTreeClassifier(max_depth=2, random_state=1)
        criados.append(modelo)
        return modelo

    X = base_anual[["x1", "x2"]]
    y = base_anual[esquema.COLUNA_ALVO]
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"])

    validacao_temporal.validar_walk_forward(criar, X, y, base_anual["ano"], janelas)

    assert len(criados) == len(janelas)
    assert len({id(modelo) for modelo in criados}) == len(janelas), (
        "alguma janela reaproveitou o modelo de outra"
    )


# --------------------------------------------------------------------------
# Divisão em três partes
# --------------------------------------------------------------------------


def test_divisao_em_tres_nao_sobrepoe(base_anual):
    treino, validacao, teste = validacao_temporal.dividir_em_tres(
        base_anual, ano_validacao=2020, ano_teste=2022
    )

    assert not (treino & validacao).any()
    assert not (validacao & teste).any()
    assert not (treino & teste).any()
    assert (treino | validacao | teste).all(), "toda linha precisa cair em algum"


def test_divisao_em_tres_respeita_a_ordem_do_tempo(base_anual):
    treino, validacao, teste = validacao_temporal.dividir_em_tres(
        base_anual, ano_validacao=2020, ano_teste=2022
    )

    assert base_anual.loc[treino, "ano"].max() < base_anual.loc[validacao, "ano"].min()
    assert base_anual.loc[validacao, "ano"].max() < base_anual.loc[teste, "ano"].min()


def test_anos_de_corte_invertidos_dao_erro(base_anual):
    with pytest.raises(ValueError, match="anterior"):
        validacao_temporal.dividir_em_tres(base_anual, ano_validacao=2023,
                                           ano_teste=2021)


def test_conjunto_vazio_da_erro_claro(base_anual):
    with pytest.raises(ValueError, match="vazio"):
        validacao_temporal.dividir_em_tres(base_anual, ano_validacao=2030,
                                           ano_teste=2031)


# --------------------------------------------------------------------------
# Escolha de hiperparâmetros
# --------------------------------------------------------------------------


def test_escolha_nao_toca_no_conjunto_de_teste(base_anual):
    """
    O modelo espião registra quais anos viu. A escolha de hiperparâmetros só
    pode enxergar treino e validação — nunca os anos de teste.
    """
    anos_vistos = set()

    class Espiao(DecisionTreeClassifier):
        def fit(self, X, y):
            anos_vistos.update(X["ano_marcador"])
            return super().fit(X, y)

    X = base_anual[["x1", "x2"]].copy()
    X["ano_marcador"] = base_anual["ano"]
    y = base_anual[esquema.COLUNA_ALVO]
    treino, validacao, teste = validacao_temporal.dividir_em_tres(
        base_anual, 2020, 2022
    )

    validacao_temporal.escolher_hiperparametros(
        lambda profundidade: Espiao(max_depth=profundidade, random_state=1),
        [{"profundidade": 2}, {"profundidade": 5}],
        X, y, treino, validacao,
    )

    anos_de_teste = set(base_anual.loc[teste, "ano"])
    assert not (anos_vistos & anos_de_teste), "a escolha viu anos do teste"


def test_parcimonia_prefere_o_modelo_simples_no_empate():
    """Diferenças dentro da tolerância são empate; vence o mais simples."""
    historico = []

    def criar(profundidade):
        historico.append(profundidade)
        return DecisionTreeClassifier(max_depth=profundidade, random_state=1)

    rng = np.random.default_rng(1)
    dados = pd.DataFrame({
        "ano": [2010] * 100 + [2020] * 100,
        "x": rng.normal(size=200),
    })
    y = pd.Series(rng.choice(["baixo", "alto"], 200))
    treino = dados["ano"] == 2010
    validacao = dados["ano"] == 2020

    escolhido, _ = validacao_temporal.escolher_hiperparametros(
        criar, [{"profundidade": 2}, {"profundidade": 20}],
        dados[["x"]], y, treino, validacao,
        tolerancia=1.0,   # tolerância enorme: tudo empata
        complexidade=lambda p: p["profundidade"],
    )

    assert escolhido["profundidade"] == 2, "deveria escolher o mais raso"


def test_sem_regra_de_parcimonia_escolhe_o_maior_valor():
    rng = np.random.default_rng(2)
    dados = pd.DataFrame({"ano": [2010] * 200 + [2020] * 200,
                          "x": rng.normal(size=400)})
    # Alvo que depende de x: árvore profunda acerta mais.
    y = pd.Series(np.where(dados["x"] > 0, "alto", "baixo"))
    treino = dados["ano"] == 2010
    validacao = dados["ano"] == 2020

    escolhido, historico = validacao_temporal.escolher_hiperparametros(
        lambda profundidade: DecisionTreeClassifier(max_depth=profundidade,
                                                    random_state=1),
        [{"profundidade": 1}, {"profundidade": 8}],
        dados[["x"]], y, treino, validacao,
        tolerancia=0.0,
    )
    melhor = max(historico, key=lambda item: item["f1_macro"])
    assert escolhido == melhor["parametros"]


def test_relatorio_traz_media_e_desvio(base_anual):
    X = base_anual[["x1", "x2"]]
    y = base_anual[esquema.COLUNA_ALVO]
    janelas = validacao_temporal.gerar_janelas(base_anual["ano"])
    resumo = validacao_temporal.validar_walk_forward(
        lambda: DecisionTreeClassifier(max_depth=3, random_state=1),
        X, y, base_anual["ano"], janelas,
    )

    texto = validacao_temporal.formatar_walk_forward(resumo)
    assert "média" in texto
    assert "desvio-padrão" in texto
    assert "pior ano" in texto
