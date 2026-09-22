"""
Testes da camada de vento.

O que estes testes realmente protegem é a aritmética circular. Direção é
ângulo, e ângulo não se soma: a média aritmética de 350° e 10° dá 180°, o
rumo exatamente oposto ao de duas medições que quase coincidem. O erro é
silencioso — não quebra nada, não levanta exceção, só desenha o mapa ao
contrário — e é por isso que ele merece teste próprio.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_VENTO = RAIZ / "dados" / "vento_estacoes.csv"

sys.path.insert(0, str(RAIZ / "dados"))

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import ESCALA_VENTO, app  # noqa: E402
from preparar_vento import direcao_do_vetor, montar  # noqa: E402
from src import inmet  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

precisa_do_vento = pytest.mark.skipif(
    not ARQUIVO_VENTO.exists(),
    reason="vento não preparado — rode: python dados/preparar_vento.py",
)


# --------------------------------------------------------------------------
# A média circular
# --------------------------------------------------------------------------


def _horas(direcoes, velocidades=None, ano=2024, mes=1):
    """Medições horárias sintéticas, no formato que `agregar_mensal` recebe."""
    if velocidades is None:
        velocidades = [5.0] * len(direcoes)
    return pd.DataFrame({
        "data": pd.to_datetime([f"{ano}-{mes:02d}-01"] * len(direcoes))
                + pd.to_timedelta(range(len(direcoes)), unit="h"),
        "precipitacao": [0.0] * len(direcoes),
        "temperatura": [25.0] * len(direcoes),
        "umidade": [80.0] * len(direcoes),
        "rajada": [0.0] * len(direcoes),
        "vento_direcao": direcoes,
        "vento_velocidade": velocidades,
    })


def _direcao_media(direcoes, velocidades=None):
    mensal = inmet.agregar_mensal(_horas(direcoes, velocidades), {})
    return float(direcao_do_vetor(mensal["vento_u_ms"], mensal["vento_v_ms"]).iloc[0])


def test_media_atravessando_o_norte_nao_aponta_para_o_sul():
    """
    O caso que a média aritmética erra por 180°.

    350° e 10° são dois ventos de norte, separados por 20 graus. Somados como
    números, dão 180° — vento de sul, o oposto exato. Somados como vetores,
    dão 0°.
    """
    assert _direcao_media([350.0, 10.0]) == pytest.approx(0.0, abs=0.5)


def test_media_sem_cruzar_o_norte_bate_com_a_aritmetica():
    """Longe da descontinuidade, o vetor concorda com a conta ingênua."""
    assert _direcao_media([80.0, 100.0]) == pytest.approx(90.0, abs=0.5)


def test_ventos_opostos_se_cancelam():
    """
    Norte e sul em partes iguais não têm rumo predominante. O que precisa
    sobrar é um vetor quase nulo — e é a constância, não a direção, que conta
    essa história depois.
    """
    mensal = inmet.agregar_mensal(_horas([0.0, 180.0]), {})
    modulo = np.hypot(mensal["vento_u_ms"].iloc[0], mensal["vento_v_ms"].iloc[0])
    assert modulo == pytest.approx(0.0, abs=0.01)


def test_o_vento_mais_forte_puxa_a_media():
    """
    As componentes já vêm multiplicadas pela velocidade, então uma hora de
    vendaval pesa mais que uma de brisa. Um vento de 10 m/s de leste contra um
    de 1 m/s de oeste tem de resultar em leste.
    """
    assert _direcao_media([90.0, 270.0], [10.0, 1.0]) == pytest.approx(90.0, abs=1.0)


def test_direcao_meteorologica_e_de_onde_o_vento_vem():
    """
    Convenção do INMET, e a que o mapa desenha: 90° é vento de LESTE, que
    sopra PARA oeste — componente u negativa. Trocar esse sinal inverteria o
    país inteiro sem quebrar teste nenhum.
    """
    mensal = inmet.agregar_mensal(_horas([90.0], [5.0]), {})
    assert mensal["vento_u_ms"].iloc[0] == pytest.approx(-5.0, abs=0.01)
    assert mensal["vento_v_ms"].iloc[0] == pytest.approx(0.0, abs=0.01)


def test_ida_e_volta_entre_angulo_e_vetor():
    """Decompor e recompor precisa devolver o mesmo ângulo, em toda a volta."""
    for graus in (0.0, 45.0, 90.0, 180.0, 270.0, 359.0):
        assert _direcao_media([graus]) == pytest.approx(graus, abs=0.5)


# --------------------------------------------------------------------------
# A constância
# --------------------------------------------------------------------------


def _montar(direcoes, velocidades=None):
    # `montar` descarta meses com menos de 240 horas medidas, porque abaixo
    # disso a predominante é ruído. O padrão é repetido até passar desse piso.
    vezes = -(-300 // len(direcoes))
    mensal = inmet.agregar_mensal(
        _horas(direcoes * vezes, (velocidades * vezes) if velocidades else None),
        {"estacao": "TESTE", "uf": "CE", "codigo": "A000",
         "latitude": -3.8, "longitude": -38.5},
    )
    mensal["ano"] = 2024
    return montar(mensal)


def test_vento_sempre_no_mesmo_rumo_tem_constancia_um():
    assert _montar([90.0])["constancia"].iloc[0] == pytest.approx(1.0, abs=0.01)


def test_vento_girando_em_todas_as_direcoes_tem_constancia_quase_zero():
    """
    Quatro rumos opostos com a mesma força: venta o tempo todo, mas sem rumo
    predominante. Sem este número, o mapa desenharia uma seta firme para um
    vento que não existe.
    """
    constancia = _montar([0.0, 90.0, 180.0, 270.0])["constancia"].iloc[0]
    assert constancia == pytest.approx(0.0, abs=0.01)


# --------------------------------------------------------------------------
# O endpoint
# --------------------------------------------------------------------------


@precisa_do_vento
def test_mes_devolve_as_estacoes_com_componentes():
    dados = cliente.get("/clima/vento?mes=9").json()

    assert dados["mes"] == 9
    assert dados["unidade"] == "m/s"
    assert dados["total_estacoes"] > 100
    assert len(dados["estacoes"]) == dados["total_estacoes"]

    # `u` e `v` vão prontos de propósito: quem anima um campo soma vetores, e
    # reconstruí-los a partir do ângulo do outro lado seria refazer
    # trigonometria que já foi feita aqui.
    primeira = dados["estacoes"][0]
    for campo in ("lat", "lon", "u", "v", "velocidade_ms", "direcao_graus",
                  "constancia"):
        assert campo in primeira


@precisa_do_vento
def test_mes_fora_da_faixa_e_recusado():
    assert cliente.get("/clima/vento?mes=0").status_code == 422
    assert cliente.get("/clima/vento?mes=13").status_code == 422


@precisa_do_vento
def test_sem_mes_usa_o_mes_de_hoje():
    assert cliente.get("/clima/vento").json()["mes"] == pd.Timestamp.today().month


@precisa_do_vento
def test_as_componentes_concordam_com_o_angulo_publicado():
    """
    `u`, `v` e `direcao_graus` descrevem a mesma coisa duas vezes. Se elas
    discordarem, o mapa (que usa as componentes) e qualquer leitura humana
    (que usa o ângulo) contariam histórias diferentes.
    """
    estacoes = cliente.get("/clima/vento?mes=6").json()["estacoes"]

    for estacao in estacoes[:50]:
        esperado = float(direcao_do_vetor(
            np.array([estacao["u"]]), np.array([estacao["v"]])
        )[0])
        # A volta é circular: 359,9° e 0,1° distam 0,2°, não 359,8°.
        diferenca = abs((estacao["direcao_graus"] - esperado + 180) % 360 - 180)
        assert diferenca < 1.0, f'{estacao["estacao"]}: {diferenca:.1f}° de erro'


@precisa_do_vento
def test_os_alisios_do_nordeste_aparecem_no_dado():
    """
    Teste de realidade, e não de código: a costa do Nordeste tem alísios, que
    sopram de leste/sudeste quase o ano inteiro. Se o pipeline inverter um
    sinal ou embaralhar estações, é aqui que aparece — nenhum outro teste
    saberia dizer que o vento de Fortaleza está errado.
    """
    estacoes = cliente.get("/clima/vento?mes=9").json()["estacoes"]
    nordeste = [e for e in estacoes if e["uf"] in ("CE", "RN")
                and e["constancia"] > 0.8]

    assert len(nordeste) >= 5, "nenhum vento constante no Nordeste em setembro"

    for estacao in nordeste:
        # De leste a sudeste, com folga generosa para o relevo local.
        assert 60 <= estacao["direcao_graus"] <= 180, (
            f'{estacao["estacao"]}: vento de {estacao["direcao_graus"]:.0f}°, '
            f"fora do rumo dos alísios"
        )
        # Vindo de leste, o ar vai para oeste: u negativo.
        assert estacao["u"] < 0


# --------------------------------------------------------------------------
# A escala
# --------------------------------------------------------------------------


def test_a_escala_cobre_qualquer_velocidade_sem_buraco():
    """
    As faixas emendam uma na outra e a última é aberta: uma velocidade entre
    duas faixas ficaria sem cor, e um vento acima do topo também.
    """
    for (_, ate, _, _), (de, *_) in zip(ESCALA_VENTO, ESCALA_VENTO[1:]):
        assert ate == de

    assert ESCALA_VENTO[0][0] == 0
    assert ESCALA_VENTO[-1][1] is None
