"""
Variáveis climáticas para o modelo de risco.

A regra que manda aqui
----------------------
As variáveis de um mês-alvo M vêm dos meses **anteriores** a ele — nunca do
próprio M. Isso não é preciosismo: se o modelo soubesse quanto choveu em
fevereiro para prever o desastre de fevereiro, ele não estaria prevendo nada,
apenas descrevendo. E na hora de usar o sistema, em janeiro, a chuva de
fevereiro ainda não existe.

O que se perde e o que se ganha com isso
----------------------------------------
Perde-se o gatilho imediato: a tempestade que causa a enchente no mesmo mês.
Ganha-se o mecanismo que realmente é previsível — **solo encharcado**. Um mês
de chuva acima do normal deixa o terreno saturado, e é nesse estado que o
deslizamento acontece na chuva seguinte. É física, e é antecipável.

Anomalia, não valor absoluto
----------------------------
200 mm em um mês é seca no litoral amazônico e dilúvio no sertão. Por isso a
variável mais importante aqui é a **anomalia**: quanto a chuva do mês passado
se afastou do normal daquele lugar naquele mês do calendário. A normal é
calculada com dados de 2000–2009, período inteiramente anterior ao estudo.
"""

import numpy as np
import pandas as pd

# Período de referência da normal climatológica. Fica antes de 2010, quando
# começa o dataset de treino, então nenhuma informação do futuro entra nela.
NORMAL_ANO_INICIAL = 2000
NORMAL_ANO_FINAL = 2009

# Colunas climáticas do mês anterior, e o nome que recebem no dataset.
DO_MES_ANTERIOR = {
    "chuva_total_mm": "chuva_mes_anterior_mm",
    "chuva_max_dia_mm": "chuva_max_dia_mes_anterior_mm",
    "dias_com_chuva": "dias_com_chuva_mes_anterior",
    "temperatura_media_c": "temperatura_mes_anterior_c",
    "umidade_media_pct": "umidade_mes_anterior_pct",
    "rajada_max_kmh": "rajada_mes_anterior_kmh",
}

COLUNAS_CLIMA = [
    *DO_MES_ANTERIOR.values(),
    "chuva_3_meses_anteriores_mm",
    "anomalia_chuva_pct",
    "meses_de_clima_disponiveis",
]


def _indice_mes(ano, mes):
    """Número contínuo de meses, para comparar datas com aritmética simples."""
    return (np.asarray(ano) - 1900) * 12 + (np.asarray(mes) - 1)


def calcular_normais_municipais(clima: pd.DataFrame,
                                ano_inicial: int = NORMAL_ANO_INICIAL,
                                ano_final: int = NORMAL_ANO_FINAL) -> pd.DataFrame:
    """
    Chuva típica de cada município em cada mês do calendário.

    É a régua contra a qual a anomalia é medida. Municípios cuja estação só
    passou a existir depois de 2009 ficam sem normal — e é melhor assim do que
    inventar uma régua com dados do próprio período que se quer prever.
    """
    referencia = clima[(clima["ano"] >= ano_inicial) & (clima["ano"] <= ano_final)]
    if referencia.empty:
        return pd.DataFrame(columns=["codigo_ibge", "mes", "chuva_normal_mm",
                                     "anos_na_normal"])

    return referencia.groupby(["codigo_ibge", "mes"]).agg(
        chuva_normal_mm=("chuva_total_mm", "mean"),
        anos_na_normal=("ano", "nunique"),
    ).reset_index()


def adicionar_features(alvos: pd.DataFrame, clima: pd.DataFrame,
                       normais: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Acrescenta as variáveis climáticas a cada linha do dataset.

    `alvos` precisa ter codigo_ibge, ano e mes. `clima` é a saída de
    `inmet.atribuir_a_municipios`. Linhas sem medição disponível ficam com
    valor nulo, que o pipeline do modelo imputa depois.
    """
    if normais is None:
        normais = calcular_normais_municipais(clima)

    alvos = alvos.copy()
    alvos["_indice"] = _indice_mes(alvos["ano"], alvos["mes"])

    fonte = clima.copy()
    fonte["_indice"] = _indice_mes(fonte["ano"], fonte["mes"])

    # --- Mês anterior (M-1) ------------------------------------------------
    anterior = fonte[["codigo_ibge", "_indice", *DO_MES_ANTERIOR]].rename(
        columns=DO_MES_ANTERIOR
    )
    anterior["_indice"] = anterior["_indice"] + 1   # passa a valer para o mês seguinte

    resultado = alvos.merge(anterior, on=["codigo_ibge", "_indice"], how="left")

    # --- Acumulado de três meses (M-3, M-2, M-1) ---------------------------
    # É o que representa solo saturado: um mês isolado de chuva forte drena,
    # três meses seguidos encharcam.
    chuva = fonte[["codigo_ibge", "_indice", "chuva_total_mm"]]
    somas = []
    for atraso in (1, 2, 3):
        deslocada = chuva.copy()
        deslocada["_indice"] = deslocada["_indice"] + atraso
        deslocada = deslocada.rename(columns={"chuva_total_mm": f"_chuva_{atraso}"})
        somas.append(deslocada)

    for parte in somas:
        resultado = resultado.merge(parte, on=["codigo_ibge", "_indice"], how="left")

    colunas_atraso = [f"_chuva_{a}" for a in (1, 2, 3)]
    resultado["chuva_3_meses_anteriores_mm"] = resultado[colunas_atraso].sum(
        axis=1, min_count=1
    )
    # Quantos dos três meses realmente têm medição: distingue "choveu pouco"
    # de "não sabemos", que é uma diferença importante.
    resultado["meses_de_clima_disponiveis"] = resultado[colunas_atraso].notna().sum(axis=1)
    resultado = resultado.drop(columns=colunas_atraso)

    # --- Anomalia em relação à normal --------------------------------------
    if not normais.empty:
        # A normal é do mês ANTERIOR, que é de onde vem a chuva comparada.
        mes_anterior = ((resultado["mes"] - 2) % 12) + 1
        referencia = resultado[["codigo_ibge"]].copy()
        referencia["mes"] = mes_anterior

        com_normal = referencia.merge(
            normais[["codigo_ibge", "mes", "chuva_normal_mm"]],
            on=["codigo_ibge", "mes"], how="left",
        )
        normal = com_normal["chuva_normal_mm"].to_numpy()

        with np.errstate(divide="ignore", invalid="ignore"):
            anomalia = np.where(
                (normal > 0) & np.isfinite(normal),
                (resultado["chuva_mes_anterior_mm"].to_numpy() / normal - 1.0) * 100.0,
                np.nan,
            )
        # Anomalias absurdas vêm de normais minúsculas (mês seco no sertão,
        # onde 5 mm viram 2000% de anomalia). O limite mantém a escala útil.
        resultado["anomalia_chuva_pct"] = np.clip(anomalia, -100.0, 500.0)
    else:
        resultado["anomalia_chuva_pct"] = np.nan

    return resultado.drop(columns=["_indice"])


def resumir_cobertura(dados: pd.DataFrame) -> dict:
    """Quanto do dataset ficou de fato com informação climática."""
    total = len(dados)
    if total == 0:
        return {"linhas": 0}

    com_chuva = int(dados["chuva_mes_anterior_mm"].notna().sum())
    com_anomalia = int(dados["anomalia_chuva_pct"].notna().sum())

    return {
        "linhas": total,
        "com_chuva_do_mes_anterior": com_chuva,
        "pct_com_chuva": round(com_chuva / total, 4),
        "com_anomalia": com_anomalia,
        "pct_com_anomalia": round(com_anomalia / total, 4),
        "tres_meses_completos": int(
            (dados["meses_de_clima_disponiveis"] == 3).sum()
        ),
    }
