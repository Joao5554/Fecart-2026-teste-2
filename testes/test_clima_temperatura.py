"""
Testes da camada de temperatura — o mapa de calor.

O que estes testes protegem é a PONDERAÇÃO. A temperatura de um período sai
de uma média de médias, e média de médias só está certa quando cada parcela
entra com o peso das horas que a produziram.

O erro é silencioso: um mês em que o termômetro funcionou uma semana pesando
igual a um mês inteiro não levanta exceção, não quebra o desenho e não
aparece na legenda — só desloca alguns graus o campo inteiro. É exatamente o
tipo de defeito que só um teste pega.

O outro ponto é a máxima e a mínima. Elas são MÉDIAS das máximas e das
mínimas diárias, não o pico absoluto do período: o pico é um registro só, e
um sensor com defeito viraria "a máxima do mês".
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_TEMPERATURA = RAIZ / "dados" / "temperatura_estacoes.csv"

sys.path.insert(0, str(RAIZ / "dados"))

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import ESCALA_TEMPERATURA, app  # noqa: E402
from preparar_temperatura import (  # noqa: E402
    TEMPERATURA_MAXIMA_PLAUSIVEL,
    TEMPERATURA_MINIMA_PLAUSIVEL,
    montar,
)
from src import inmet  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

precisa_da_temperatura = pytest.mark.skipif(
    not ARQUIVO_TEMPERATURA.exists(),
    reason="temperatura não preparada — rode: python dados/preparar_temperatura.py",
)


# --------------------------------------------------------------------------
# A agregação horária
# --------------------------------------------------------------------------


def _horas(temperaturas, ano=2024, mes=1):
    """Medições horárias sintéticas, no formato que `agregar_mensal` recebe."""
    return pd.DataFrame({
        "data": pd.to_datetime([f"{ano}-{mes:02d}-01"] * len(temperaturas))
                + pd.to_timedelta(range(len(temperaturas)), unit="h"),
        "precipitacao": [0.0] * len(temperaturas),
        "temperatura": temperaturas,
        "umidade": [80.0] * len(temperaturas),
        "rajada": [0.0] * len(temperaturas),
        "vento_direcao": [0.0] * len(temperaturas),
        "vento_velocidade": [0.0] * len(temperaturas),
    })


def test_a_media_do_mes_e_a_media_das_horas():
    mensal = inmet.agregar_mensal(_horas([20.0, 22.0, 24.0, 26.0]), {})
    assert mensal["temperatura_media_c"].iloc[0] == pytest.approx(23.0)


def test_a_maxima_do_mes_e_a_media_das_maximas_diarias():
    """
    Dois dias: um que vai a 30 °C, outro a 20 °C. A máxima do mês é 25 — a
    média das duas —, e não 30, que é o pico absoluto.

    A diferença existe para um motivo prático: o pico absoluto de um mês é um
    único registro, e um sensor com uma leitura maluca viraria "a máxima".
    A média de trinta máximas diárias absorve o erro de uma delas.
    """
    primeiro_dia = _horas([10.0, 30.0], ano=2024, mes=1)
    segundo_dia = _horas([10.0, 20.0], ano=2024, mes=1)
    segundo_dia["data"] = segundo_dia["data"] + pd.Timedelta(days=1)

    mensal = inmet.agregar_mensal(
        pd.concat([primeiro_dia, segundo_dia], ignore_index=True), {}
    )

    assert mensal["temperatura_max_c"].iloc[0] == pytest.approx(25.0)
    assert mensal["temperatura_min_c"].iloc[0] == pytest.approx(10.0)


def test_as_horas_de_temperatura_sao_contadas_a_parte():
    """
    O termômetro e o pluviômetro falham em momentos diferentes: um mês pode
    ter chuva completa e temperatura pela metade. Sem contagem própria, um mês
    de termômetro quebrado entraria na climatologia com peso de mês inteiro.
    """
    medicoes = _horas([20.0, None, 24.0, None])
    mensal = inmet.agregar_mensal(medicoes, {})

    assert mensal["temperatura_horas"].iloc[0] == 2
    assert mensal["horas_registradas"].iloc[0] == 4


def test_a_altitude_da_estacao_acompanha_a_medicao():
    """
    É a altitude que explica a mancha fria dentro de uma região quente. Sem
    ela, a serra no meio do mapa parece erro de interpolação.
    """
    mensal = inmet.agregar_mensal(_horas([20.0]), {"altitude": 1161.0})
    assert mensal["altitude"].iloc[0] == pytest.approx(1161.0)


# --------------------------------------------------------------------------
# O preparo da base
# --------------------------------------------------------------------------


def _mensal(linhas):
    """Linhas no formato que `carregar_pasta` devolve, prontas para `montar`."""
    padrao = {
        "codigo_estacao": "A001", "estacao": "TESTE", "uf": "DF",
        "ano": 2024, "mes": 1, "latitude": -15.0, "longitude": -47.0,
        "altitude": 1000.0, "temperatura_media_c": 25.0,
        "temperatura_max_c": 30.0, "temperatura_min_c": 20.0,
        "temperatura_horas": 720,
    }
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


def test_mes_quase_sem_medicao_fica_de_fora():
    """
    Estação que funcionou dois dias no mês não descreve o mês. O corte são
    240 horas — dez dias de medição contínua, o mesmo da camada de vento.
    """
    saida = montar(_mensal([
        {"mes": 1, "temperatura_horas": 720},
        {"mes": 2, "temperatura_horas": 48},
    ]))

    assert list(saida["mes"]) == [1]


def test_sensor_com_defeito_e_descartado():
    """
    Existe -9999 tratado na leitura, mas existe também o sensor que grava
    60 °C o mês inteiro. Sem o corte, uma estação assim envenena a
    interpolação de uma região inteira.
    """
    saida = montar(_mensal([
        {"mes": 1, "temperatura_media_c": 25.0},
        {"mes": 2, "temperatura_media_c": TEMPERATURA_MAXIMA_PLAUSIVEL + 10},
        {"mes": 3, "temperatura_media_c": TEMPERATURA_MINIMA_PLAUSIVEL - 10},
    ]))

    assert list(saida["mes"]) == [1]


def test_a_media_de_linhas_repetidas_e_ponderada_pelas_horas():
    """
    A mesma estação aparece duas vezes no mesmo mês quando o ano foi baixado
    solto e dentro de um ZIP. Juntar as duas é uma média PONDERADA: 700 horas
    a 30 °C e 100 horas a 20 °C dão 28,75 °C, não 25.
    """
    saida = montar(_mensal([
        {"mes": 1, "temperatura_media_c": 30.0, "temperatura_horas": 700},
        {"mes": 1, "temperatura_media_c": 20.0, "temperatura_horas": 100},
    ]))

    assert len(saida) == 1
    esperado = (30.0 * 700 + 20.0 * 100) / 800
    assert saida["temperatura_media_c"].iloc[0] == pytest.approx(esperado, abs=0.01)


def test_estacao_sem_coordenada_nao_entra():
    """O mapa é o único consumidor da base; ponto sem lugar não se desenha."""
    saida = montar(_mensal([
        {"mes": 1, "codigo_estacao": "A001"},
        {"mes": 1, "codigo_estacao": "A002", "latitude": None},
    ]))

    assert list(saida["codigo_estacao"]) == ["A001"]


def test_a_base_guarda_ano_e_mes():
    """
    É o que permite ao mesmo arquivo responder às três perguntas dos mapas: o
    mês típico, o ano inteiro, e um mês específico de um ano específico.
    """
    saida = montar(_mensal([
        {"ano": 2023, "mes": 1}, {"ano": 2024, "mes": 1},
    ]))

    assert list(saida["ano"]) == [2023, 2024]


# --------------------------------------------------------------------------
# A escala de cor
# --------------------------------------------------------------------------


def test_a_escala_cobre_o_que_o_brasil_mede():
    """
    De 0 °C (a geada da serra catarinense em julho) a mais de 36 °C (o sertão
    em novembro). Uma escala de -40 a 50 gastaria metade das cores em
    temperaturas que nunca aparecem, e o país inteiro sairia do mesmo tom.
    """
    assert ESCALA_TEMPERATURA[0][0] == 0
    assert ESCALA_TEMPERATURA[-1][1] is None, "a última faixa precisa ser aberta"
    assert ESCALA_TEMPERATURA[-1][0] >= 35


def test_as_faixas_da_escala_sao_continuas():
    """Buraco entre faixas é temperatura sem cor definida."""
    for anterior, seguinte in zip(ESCALA_TEMPERATURA, ESCALA_TEMPERATURA[1:]):
        assert anterior[1] == seguinte[0], (
            f"a faixa que termina em {anterior[1]} não emenda "
            f"na que começa em {seguinte[0]}"
        )


# --------------------------------------------------------------------------
# O endpoint
# --------------------------------------------------------------------------


@precisa_da_temperatura
def test_o_mes_sem_ano_devolve_a_climatologia():
    """
    É o que os mapas de previsão pedem: eles estimam o risco de um mês que
    ainda não chegou, e a temperatura de um mês futuro não existe. Pedir
    "fevereiro" tem de devolver o fevereiro de sempre.
    """
    resposta = cliente.get("/clima/temperatura?mes=2")
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["mes"] == 2
    assert corpo["ano"] is None
    assert corpo["estacoes"], "nenhuma estação na resposta"
    # O período precisa dizer que é média de vários anos, para a tela nunca
    # apresentar a climatologia como se fosse a medição de um mês só.
    assert "média" in corpo["periodo"]


@precisa_da_temperatura
def test_o_ano_sem_mes_devolve_a_media_do_ano():
    corpo = cliente.get("/clima/temperatura").json()
    ultimo = corpo["cobertura"]["ultimo_ano"]

    resposta = cliente.get(f"/clima/temperatura?ano={ultimo}")
    assert resposta.status_code == 200
    assert resposta.json()["ano"] == ultimo


@precisa_da_temperatura
def test_o_periodo_cabe_na_frase_que_o_usa():
    """
    O rodapé da camada escreve "Temperatura do ar ... em {periodo}". Um
    período escrito como "o ano de 2024" produziria "em o ano de 2024" na
    tela — erro que nenhum teste de formato pegaria, porque o campo está lá
    e tem o valor certo.
    """
    corpo = cliente.get("/clima/temperatura").json()
    ultimo = corpo["cobertura"]["ultimo_ano"]

    for parametros in (f"ano={ultimo}", "mes=3", f"ano={ultimo}&mes=3"):
        periodo = cliente.get(f"/clima/temperatura?{parametros}").json()["periodo"]
        assert not periodo.startswith(("o ", "a ", "os ", "as ")), (
            f"'em {periodo}' não é português"
        )


@precisa_da_temperatura
def test_a_grandeza_nao_se_diz_do_mes():
    """
    A mesma grandeza serve ao mês típico, ao ano inteiro e a um mês
    específico. Chamá-la de "média do mês" produziria "média do mês em 2024".
    """
    for grandeza in ("media", "maxima", "minima"):
        corpo = cliente.get(f"/clima/temperatura?mes=1&grandeza={grandeza}").json()
        assert "do mês" not in corpo["descricao_grandeza"]


@precisa_da_temperatura
def test_cada_estacao_aparece_uma_vez_so():
    """
    O recorte de um mês típico tem uma linha por estação POR ANO. Sem a
    agregação, a mesma estação viraria cinco pontos empilhados no mesmo pixel
    — e a interpolação daria a ela cinco vezes o peso das vizinhas.
    """
    corpo = cliente.get("/clima/temperatura?mes=1").json()
    nomes = [(e["estacao"], e["uf"]) for e in corpo["estacoes"]]

    assert len(nomes) == len(set(nomes))
    assert corpo["total_estacoes"] == len(nomes)


@precisa_da_temperatura
def test_as_temperaturas_sao_plausiveis():
    corpo = cliente.get("/clima/temperatura?mes=7").json()
    for estacao in corpo["estacoes"]:
        assert -10 <= estacao["temperatura_c"] <= 45, (
            f"{estacao['estacao']}/{estacao['uf']}: "
            f"{estacao['temperatura_c']} °C"
        )


@precisa_da_temperatura
def test_julho_e_mais_frio_que_janeiro():
    """
    O teste de sanidade mais simples que existe para esta base, e o que pega
    um erro de agregação que nenhuma checagem de formato pegaria: se o
    agrupamento misturar meses, os dois saem iguais.
    """
    janeiro = cliente.get("/clima/temperatura?mes=1").json()
    julho = cliente.get("/clima/temperatura?mes=7").json()

    assert julho["temperatura_media_c"] < janeiro["temperatura_media_c"]


@precisa_da_temperatura
def test_a_serra_e_mais_fria_que_a_planicie_equatorial():
    """
    Sanidade geográfica, e é o teste que pega latitude e longitude trocadas
    em algum ponto do caminho — nenhum outro pegaria.

    A checagem NÃO é por estado. A estação mais fria do Brasil em julho é
    Itatiaia (RJ), a 2.450 m, e uma lista de "estados frios" reprovaria o
    dado certo. O que vale é o mecanismo: frio no Brasil é altitude ou
    latitude sul, e as duas juntas em Itatiaia, Morro da Igreja e Campos do
    Jordão. Calor é o contrário — norte e perto do nível do mar.
    """
    corpo = cliente.get("/clima/temperatura?mes=7").json()
    por_nome = {e["estacao"]: e for e in corpo["estacoes"]}

    fria = por_nome[corpo["mais_fria"]["estacao"]]
    quente = por_nome[corpo["mais_quente"]["estacao"]]

    assert fria["altitude_m"] > 800 or fria["lat"] < -25, (
        f"a mais fria ({fria['estacao']}) não é nem serra nem sul: "
        f"{fria['altitude_m']} m, latitude {fria['lat']}"
    )
    assert quente["lat"] > -20 and quente["altitude_m"] < 600, (
        f"a mais quente ({quente['estacao']}) não é nem norte nem baixa: "
        f"{quente['altitude_m']} m, latitude {quente['lat']}"
    )
    assert fria["temperatura_c"] < 15 < quente["temperatura_c"]


@precisa_da_temperatura
def test_a_altitude_vai_na_resposta():
    """É ela que explica a mancha fria; sem ela a serra parece erro."""
    corpo = cliente.get("/clima/temperatura?mes=1").json()
    com_altitude = [e for e in corpo["estacoes"] if e["altitude_m"] is not None]

    assert len(com_altitude) > len(corpo["estacoes"]) * 0.9
    assert max(e["altitude_m"] for e in com_altitude) > 800


@precisa_da_temperatura
def test_a_maxima_e_maior_que_a_media_que_e_maior_que_a_minima():
    """As três grandezas do mesmo mês, na ordem que a física exige."""
    pedir = lambda g: cliente.get(  # noqa: E731
        f"/clima/temperatura?mes=1&grandeza={g}"
    ).json()["temperatura_media_c"]

    assert pedir("minima") < pedir("media") < pedir("maxima")


@precisa_da_temperatura
def test_grandeza_desconhecida_e_recusada():
    resposta = cliente.get("/clima/temperatura?mes=1&grandeza=sensacao")
    assert resposta.status_code == 422


@precisa_da_temperatura
def test_mes_fora_da_faixa_e_recusado():
    assert cliente.get("/clima/temperatura?mes=13").status_code == 422
    assert cliente.get("/clima/temperatura?mes=0").status_code == 422


@precisa_da_temperatura
def test_ano_sem_medicao_explica_a_cobertura():
    """
    A rede automática do INMET não existia em 1995, e a base preparada começa
    depois disso. O 404 precisa dizer qual é o período coberto — senão quem
    pediu não sabe o que pedir em seguida.
    """
    resposta = cliente.get("/clima/temperatura?ano=1995")
    assert resposta.status_code == 404
    assert "temperatura" in resposta.json()["detail"].lower()


@precisa_da_temperatura
def test_a_escala_vai_junto_com_os_dados():
    """A legenda do mapa é montada a partir dela; separadas, saem de sincronia."""
    corpo = cliente.get("/clima/temperatura?mes=1").json()

    assert corpo["unidade"] == "°C"
    assert len(corpo["escala"]) == len(ESCALA_TEMPERATURA)
    assert corpo["escala"][0]["cor"].startswith("#")
