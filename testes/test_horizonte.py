"""
O que acontece quando se pergunta por um mês que a base ainda não alcançou.

A interface passou a oferecer meses de setembro de 2026 a dezembro de 2027,
enquanto o Atlas termina em 2025. As variáveis de janela móvel contam o que
aconteceu nos 12, 24 e 60 meses ANTERIORES ao mês pedido — e uma janela de 12
meses a partir de um mês de 2027 cai inteira num período sem registro.

`src/atlas._ancora` resolve isso parando as janelas no fim da base. Estes
testes travam as duas metades da promessa:

  1. para meses DENTRO da base — ou seja, para o treino inteiro — nada muda;
  2. para meses FORA dela, as contagens param em vez de zerar.
"""

import numpy as np
import pandas as pd
import pytest

from src import atlas


@pytest.fixture
def historico(ocorrencias):
    return atlas.agregar_por_mes(ocorrencias)


def _alvo(ibge, grupo, ano, mes):
    return pd.DataFrame([{
        "codigo_ibge": ibge,
        "grupo_desastre": grupo,
        "indice_mes": int(atlas._indice_mes(ano, mes)),
    }])


def _sem_ancora(monkeypatch):
    """Devolve o comportamento antigo: a janela anda para onde o alvo mandar."""
    monkeypatch.setattr(atlas, "_ancora", lambda historico, meses: meses)


# --------------------------------------------------------------------------
# 1. Dentro da base, a âncora não existe
# --------------------------------------------------------------------------


def test_ancora_devolve_o_proprio_mes_quando_ele_esta_na_base(historico):
    dentro = atlas._indice_mes(2020, 5)
    assert atlas._ancora(historico, np.array([dentro]))[0] == dentro


def test_ancora_nao_ultrapassa_o_fim_da_base(historico):
    ultimo = int(historico["indice_mes"].max())
    futuro = atlas._indice_mes(2027, 12)

    ancorado = atlas._ancora(historico, np.array([futuro]))[0]

    # Para o mês SEGUINTE ao último registro: as janelas contam o que é
    # estritamente anterior ao alvo, e é assim que o último mês entra na conta.
    assert ancorado == ultimo + 1


def test_features_do_passado_nao_mudam_com_a_ancora(monkeypatch, ocorrencias):
    """
    A garantia que sustenta tudo: o dataset de treino continua idêntico.

    Se a âncora alterasse uma linha que seja do treino, o modelo salvo passaria
    a ser treinado com uma conta e consultado com outra — exatamente o que
    `calcular_features` existe para impedir.
    """
    com = atlas.construir_dataset(ocorrencias, ano_inicial=2015, ano_final=2025,
                                  negativos_por_positivo=2, semente=7)

    _sem_ancora(monkeypatch)
    sem = atlas.construir_dataset(ocorrencias, ano_inicial=2015, ano_final=2025,
                                  negativos_por_positivo=2, semente=7)

    pd.testing.assert_frame_equal(com, sem)


# --------------------------------------------------------------------------
# 2. Fora da base, a janela para em vez de zerar
# --------------------------------------------------------------------------


def test_mes_futuro_zerava_a_janela_de_12_meses(monkeypatch, historico):
    """O defeito, reproduzido: sem âncora, 2027 via um país sem histórico."""
    _sem_ancora(monkeypatch)

    linha = atlas.calcular_features(
        historico, _alvo(3303906, "DESLIZAMENTO", 2027, 6)
    ).iloc[0]

    assert linha["ocorrencias_12m"] == 0
    assert linha["ocorrencias_municipio_12m"] == 0


def test_mes_futuro_mantem_o_que_a_base_sabe(historico):
    """Com âncora, a mesma consulta enxerga o último ano registrado."""
    linha = atlas.calcular_features(
        historico, _alvo(3303906, "DESLIZAMENTO", 2027, 6)
    ).iloc[0]

    assert linha["ocorrencias_12m"] > 0
    assert linha["ocorrencias_total_historico"] > 0


def test_o_futuro_ve_exatamente_o_fim_da_base(historico):
    """
    Um mês futuro responde como o primeiro mês sem dado, e não como outro.

    É a definição da hipótese assumida: o que não se observa recebe a última
    observação disponível.
    """
    futuro = atlas.calcular_features(
        historico, _alvo(2311306, "ESTIAGEM_SECA", 2027, 9)
    ).iloc[0]
    fim_da_base = atlas.calcular_features(
        historico, _alvo(2311306, "ESTIAGEM_SECA", 2026, 1)
    ).iloc[0]

    for coluna in ("ocorrencias_12m", "ocorrencias_24m", "ocorrencias_60m",
                   "ocorrencias_total_historico", "ocorrencias_municipio_12m",
                   "ocorrencias_uf_grupo_12m", "meses_desde_ultima_ocorrencia"):
        assert futuro[coluna] == fim_da_base[coluna], coluna


def test_a_sazonalidade_continua_valendo_no_futuro(historico):
    """
    O mês do calendário vem do alvo, não da âncora.

    Se a âncora também congelasse isso, todos os meses futuros teriam a mesma
    resposta e a previsão perderia a única coisa que ela ainda sabe: a época
    do ano em que aquele desastre costuma acontecer.
    """
    setembro = atlas.calcular_features(
        historico, _alvo(2311306, "ESTIAGEM_SECA", 2027, 9)
    ).iloc[0]
    abril = atlas.calcular_features(
        historico, _alvo(2311306, "ESTIAGEM_SECA", 2027, 4)
    ).iloc[0]

    # A seca de Quixadá é sempre em agosto, setembro e outubro.
    assert setembro["ocorrencias_mesmo_mes_historico"] > 0
    assert abril["ocorrencias_mesmo_mes_historico"] == 0


def test_o_mesmo_mes_de_2026_e_de_2027_da_a_mesma_resposta(historico):
    """
    A consequência honesta da correção, registrada como comportamento.

    Sem dado novo, não existe nada que distinga setembro de 2026 de setembro
    de 2027. Se um dia a base for atualizada, este teste passa a falhar — e é
    esse o sinal de que a janela de previsão pode andar para frente.
    """
    em_2026 = atlas.calcular_features(
        historico, _alvo(4202404, "INUNDACAO", 2026, 11)
    ).iloc[0]
    em_2027 = atlas.calcular_features(
        historico, _alvo(4202404, "INUNDACAO", 2027, 11)
    ).iloc[0]

    iguais = [c for c in em_2026.index if c != "indice_mes"]
    pd.testing.assert_series_equal(em_2026[iguais], em_2027[iguais],
                                   check_names=False)
