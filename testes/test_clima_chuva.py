"""
Testes da camada de chuva medida.

O endpoint serve os PONTOS de medição do INMET, e não valores por município.
A diferença é o motivo de ele existir: no `clima_mensal.csv`, que alimenta o
modelo, 92% das linhas carregam a chuva de uma estação de outro município —
só 8% do país tem estação própria. Isso serve como variável de entrada, mas
desenhar um mapa com esses valores afirmaria uma medição que nunca foi feita
ali. Os testes abaixo protegem essa separação.
"""

from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ESTACOES = RAIZ / "dados" / "clima_estacoes.csv"

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import (  # noqa: E402
    ESCALA_CHUVA_ANO,
    ESCALA_CHUVA_MES,
    app,
)

cliente = fastapi_testclient.TestClient(app)

precisa_do_clima = pytest.mark.skipif(
    not ARQUIVO_ESTACOES.exists(),
    reason="clima não preparado — rode: python dados/preparar_clima.py",
)


@pytest.fixture(scope="module")
def ano_cheio():
    return cliente.get("/clima/chuva?ano=2024").json()


# --------------------------------------------------------------------------
# Formato e conteúdo
# --------------------------------------------------------------------------


@precisa_do_clima
def test_resposta_traz_o_que_o_mapa_precisa(ano_cheio):
    for campo in ("ano", "periodo", "unidade", "cobertura", "total_estacoes",
                  "escala", "estacoes"):
        assert campo in ano_cheio, f"falta '{campo}'"

    assert ano_cheio["unidade"] == "mm"
    assert ano_cheio["estacoes"], "nenhuma estação devolvida"


@precisa_do_clima
def test_toda_estacao_tem_coordenada_dentro_do_brasil(ano_cheio):
    """
    Sem coordenada não há onde desenhar; fora do Brasil, a estação puxaria a
    interpolação para o oceano.
    """
    for estacao in ano_cheio["estacoes"]:
        assert -34.0 <= estacao["lat"] <= 6.0, estacao
        assert -74.0 <= estacao["lon"] <= -32.0, estacao


@precisa_do_clima
def test_cada_estacao_aparece_uma_vez_so(ano_cheio):
    nomes = [(e["estacao"], e["uf"]) for e in ano_cheio["estacoes"]]
    assert len(nomes) == len(set(nomes))
    assert len(nomes) == ano_cheio["total_estacoes"]


@precisa_do_clima
def test_chuva_nunca_e_negativa(ano_cheio):
    assert all(e["chuva_mm"] >= 0 for e in ano_cheio["estacoes"])


@precisa_do_clima
def test_periodo_sempre_vem_escrito(ano_cheio):
    """
    A tela nunca pode mostrar uma medição sem dizer de quando ela é — o mapa
    de risco prevê um ano que ainda não aconteceu, e a chuva ao lado dele é
    sempre de outro período.
    """
    assert ano_cheio["periodo"] == "2024"

    mensal = cliente.get("/clima/chuva?ano=2024&mes=3").json()
    assert mensal["periodo"] == "março de 2024"


# --------------------------------------------------------------------------
# Mês, ano e o valor padrão
# --------------------------------------------------------------------------


@precisa_do_clima
def test_sem_ano_usa_o_mais_recente_medido(ano_cheio):
    """O mapa de risco pede só o mês: chuva do ano que ele prevê não existe."""
    resposta = cliente.get("/clima/chuva?mes=3").json()
    assert resposta["ano"] == ano_cheio["cobertura"]["ultimo_ano"]
    assert str(resposta["ano"]) in resposta["periodo"]


@precisa_do_clima
def test_o_ano_acumula_os_meses(ano_cheio):
    """A chuva do ano de uma estação é a soma dos seus meses, não a média."""
    marco = cliente.get("/clima/chuva?ano=2024&mes=3").json()
    por_estacao = {e["estacao"]: e["chuva_mm"] for e in ano_cheio["estacoes"]}

    for estacao in marco["estacoes"][:40]:
        anual = por_estacao.get(estacao["estacao"])
        if anual is None:
            continue
        assert anual >= estacao["chuva_mm"] - 0.05, (
            f"{estacao['estacao']}: março ({estacao['chuva_mm']}) maior que "
            f"o ano inteiro ({anual})"
        )


@precisa_do_clima
def test_a_escala_muda_entre_mes_e_ano():
    """Um mês de 200 mm é chuvoso; um ano de 200 mm é semiárido."""
    mensal = cliente.get("/clima/chuva?ano=2024&mes=3").json()
    anual = cliente.get("/clima/chuva?ano=2024").json()

    assert mensal["escala"] != anual["escala"]
    assert anual["escala"][-1]["de"] > mensal["escala"][-1]["de"]


@precisa_do_clima
def test_os_numeros_batem_com_o_csv(ano_cheio):
    """Conferência direta no arquivo, sem passar pela API.

    A estação é identificada pelo par (nome, UF), nunca só pelo nome: o INMET
    tem São Simão em GO e em SP, e Valença na BA e no RJ. Contando só o nome,
    duas estações a centenas de quilômetros virariam uma — e a interpolação
    puxaria a chuva de um estado para o outro.
    """
    bruto = pd.read_csv(ARQUIVO_ESTACOES)
    de_2024 = bruto[bruto["ano"] == 2024]

    assert ano_cheio["total_estacoes"] == len(
        de_2024[["estacao", "uf"]].drop_duplicates()
    )

    soma_api = sum(e["chuva_mm"] for e in ano_cheio["estacoes"])
    assert soma_api == pytest.approx(de_2024["chuva_total_mm"].sum(), rel=1e-3)


# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------


@precisa_do_clima
def test_ano_antes_das_estacoes_explica_o_periodo():
    """
    A rede automática do INMET começa em 2000, mas o mapa por ano vai a 1991.
    Quem escolher 1995 precisa entender por que não há chuva — e não achar
    que choveu zero.
    """
    resposta = cliente.get("/clima/chuva?ano=1995")

    assert resposta.status_code == 404
    detalhe = resposta.json()["detail"]
    assert "1995" in detalhe and "2000" in detalhe


@precisa_do_clima
def test_mes_invalido_e_rejeitado():
    assert cliente.get("/clima/chuva?ano=2024&mes=13").status_code == 422


# --------------------------------------------------------------------------
# As escalas de cor
# --------------------------------------------------------------------------


@pytest.mark.parametrize("escala", [ESCALA_CHUVA_MES, ESCALA_CHUVA_ANO])
def test_as_faixas_cobrem_qualquer_valor_sem_sobrepor(escala):
    for milimetros in (0, 1, 4.9, 5, 120, 999, 5000):
        casam = [
            (de, ate) for de, ate, _, _ in escala
            if milimetros >= de and (ate is None or milimetros < ate)
        ]
        assert len(casam) == 1, f"{milimetros} mm casa com {casam}"


@pytest.mark.parametrize("escala", [ESCALA_CHUVA_MES, ESCALA_CHUVA_ANO])
def test_as_faixas_sao_continuas(escala):
    """Buraco entre faixas deixaria uma parte do mapa sem cor."""
    for (_, fim, _, _), (inicio, _, _, _) in zip(escala, escala[1:]):
        assert fim == inicio, f"salto entre {fim} e {inicio}"


def test_a_escala_de_chuva_nao_se_confunde_com_a_de_risco():
    """
    Verde, amarelo e vermelho significam nível de risco no resto do site.
    Se a chuva usasse as mesmas cores, a camada por cima do mapa de risco
    ficaria ilegível — e pior, parecendo a mesma informação.
    """
    from src import esquema

    do_risco = {c.upper() for c in esquema.CORES_RISCO.values()}
    for escala in (ESCALA_CHUVA_MES, ESCALA_CHUVA_ANO):
        do_clima = {cor.upper() for _, _, cor, _ in escala}
        assert not (do_clima & do_risco)
