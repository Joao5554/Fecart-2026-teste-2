"""
Preparação das features (características) que o modelo enxerga.

Duas responsabilidades:

1. `adicionar_derivadas` — calcula colunas que não vêm no CSV, mas ajudam o
   modelo (ciclicidade do mês, intensidade da chuva, etc.).
2. `construir_preprocessador` — monta o passo de pré-processamento do sklearn
   (imputação de valores faltantes + one-hot das categóricas).

Tudo isso vira parte do Pipeline salvo no modelo.pkl. Assim o backend aplica
exatamente as mesmas transformações do treino — sem risco de divergência.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from src import esquema


def adicionar_derivadas(dados: pd.DataFrame) -> pd.DataFrame:
    """Devolve uma cópia dos dados com as colunas derivadas calculadas.

    Aplicado no treino e na previsão, sempre da mesma forma.
    """
    dados = dados.copy()

    # O mês é cíclico: dezembro (12) está a um mês de janeiro (1), não a onze.
    # Seno e cosseno preservam essa vizinhança.
    angulo = 2 * np.pi * dados["mes"] / 12
    dados["mes_seno"] = np.sin(angulo)
    dados["mes_cosseno"] = np.cos(angulo)

    # Frequência: 10 ocorrências em 30 anos é muito diferente de 10 em 3 anos.
    anos = dados["anos_de_historico"].clip(lower=1.0)
    dados["ocorrencias_por_ano"] = (
        dados["ocorrencias_total_historico"] / anos
    ).fillna(0.0)

    # Que fração dos eventos passados foi grave o bastante para virar
    # emergência oficial. Separa município que sofre eventos pequenos e
    # frequentes de outro que sofre poucos, porém graves.
    total = dados["ocorrencias_total_historico"].replace(0, np.nan)
    dados["proporcao_reconhecidas"] = (
        dados["reconhecimentos_historico"] / total
    ).fillna(0.0).clip(0.0, 1.0)

    # Porte típico do evento naquele município.
    dados["gravidade_media_historica"] = (
        dados["afetados_historico"] / total
    ).fillna(0.0)

    return dados


def construir_preprocessador() -> ColumnTransformer:
    """Monta o pré-processamento: imputação + one-hot.

    Numéricas  -> preenche faltantes com a mediana (robusta a outliers, e
                  dados de estação meteorológica têm bastante outlier).
    Categóricas-> preenche faltantes com a categoria mais frequente e aplica
                  one-hot. `handle_unknown="ignore"` evita que a API quebre se
                  chegar uma UF ou um grupo COBRADE que não apareceu no treino.

    Random Forest não precisa de padronização de escala, então não há
    StandardScaler aqui de propósito.
    """
    # keep_empty_features mantém a coluna mesmo quando ela está inteiramente
    # vazia — é o caso de quem treina sem ter baixado os dados do INMET. Sem
    # isso, a coluna seria descartada e o número de features mudaria conforme
    # a máquina, quebrando a correspondência com os nomes na hora de reportar
    # a importância das variáveis.
    numerico = Pipeline([
        ("imputacao", SimpleImputer(strategy="median", keep_empty_features=True)),
    ])

    categorico = Pipeline([
        ("imputacao", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    return ColumnTransformer(
        transformers=[
            ("num", numerico, esquema.COLUNAS_MODELO_NUMERICAS),
            ("cat", categorico, esquema.COLUNAS_MODELO_CATEGORICAS),
        ],
        remainder="drop",  # descarta identificação (codigo_ibge, municipio, ano)
        verbose_feature_names_out=False,
    )


def separar_x_y(dados: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Separa as features do alvo, já com as derivadas calculadas."""
    dados = adicionar_derivadas(dados)
    colunas_entrada = (
        esquema.COLUNAS_MODELO_NUMERICAS + esquema.COLUNAS_MODELO_CATEGORICAS
    )
    return dados[colunas_entrada], dados[esquema.COLUNA_ALVO]


def preparar_para_previsao(dados: pd.DataFrame) -> pd.DataFrame:
    """
    Prepara linhas novas (sem alvo) para passar pelo modelo.

    Colunas que o chamador não informou entram vazias em vez de causar erro.
    É o que permite consultar a API sem os dados de clima: o pipeline imputa
    o que falta, e a resposta sai com a informação disponível.
    """
    dados = adicionar_derivadas(dados)
    colunas_entrada = (
        esquema.COLUNAS_MODELO_NUMERICAS + esquema.COLUNAS_MODELO_CATEGORICAS
    )
    return dados.reindex(columns=colunas_entrada)


def importancia_por_coluna_original(
    nomes_transformados: list[str],
    importancias: np.ndarray,
) -> dict[str, float]:
    """Agrega a importância das colunas one-hot de volta à coluna original.

    O one-hot transforma `uf` em 27 colunas (uf_AC, uf_AL, ...). Somar essas
    27 devolve a importância real da variável `uf`, que é o que interessa
    reportar.
    """
    total: dict[str, float] = {}

    for nome, valor in zip(nomes_transformados, importancias):
        original = nome
        for coluna in esquema.COLUNAS_MODELO_CATEGORICAS:
            if nome.startswith(f"{coluna}_"):
                original = coluna
                break
        total[original] = total.get(original, 0.0) + float(valor)

    return dict(sorted(total.items(), key=lambda item: item[1], reverse=True))
