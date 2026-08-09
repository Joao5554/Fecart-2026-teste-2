"""
Pré-processamento e validação dos dados.

Ponto importante do projeto: o pré-processamento é montado como uma
Pipeline do scikit-learn e salvo DENTRO do modelo.pkl, junto com o
Random Forest. Assim a API aplica exatamente as mesmas transformações
usadas no treino, sem risco de divergência entre treinar e prever.
"""

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from treinamento.esquema import (
    COLUNA_ALVO,
    COLUNAS_CATEGORICAS,
    COLUNAS_NUMERICAS,
    COLUNAS_POR_NOME,
    NOMES_COLUNAS,
)


class DadosInvalidosError(ValueError):
    """Erro levantado quando os dados não seguem o esquema do projeto."""


def validar_dados(dados: pd.DataFrame, exigir_alvo: bool = True) -> None:
    """
    Confere se o DataFrame segue o contrato definido em esquema.py.

    Falha cedo e com mensagem clara: é preferível o treinamento parar
    aqui a gerar um modelo silenciosamente errado.
    """
    esperadas = set(NOMES_COLUNAS)
    if exigir_alvo:
        esperadas.add(COLUNA_ALVO)

    faltando = esperadas - set(dados.columns)
    if faltando:
        raise DadosInvalidosError(
            "Colunas obrigatórias ausentes nos dados: "
            + ", ".join(sorted(faltando))
            + "\nConfira o esquema em treinamento/esquema.py e o arquivo CSV."
        )

    if len(dados) == 0:
        raise DadosInvalidosError("O arquivo de dados está vazio.")

    for nome in COLUNAS_NUMERICAS:
        if not pd.api.types.is_numeric_dtype(dados[nome]):
            raise DadosInvalidosError(
                f"A coluna '{nome}' deveria ser numérica, mas veio como "
                f"'{dados[nome].dtype}'. Verifique separador decimal e valores de texto."
            )

    # Valores fora da faixa não interrompem o treino (dados reais têm outliers),
    # mas são avisados para revisão humana.
    for nome in COLUNAS_NUMERICAS:
        coluna = COLUNAS_POR_NOME[nome]
        if coluna.minimo is None or coluna.maximo is None:
            continue
        fora = (
            (dados[nome] < coluna.minimo) | (dados[nome] > coluna.maximo)
        ).sum()
        if fora:
            print(
                f"  [aviso] {fora} valor(es) de '{nome}' fora da faixa "
                f"[{coluna.minimo}, {coluna.maximo}]"
            )


def separar_x_y(dados: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Separa as colunas de entrada (X) da coluna alvo (y), na ordem do esquema."""
    X = dados[list(NOMES_COLUNAS)].copy()
    y = dados[COLUNA_ALVO].copy()
    return X, y


def criar_preprocessador() -> ColumnTransformer:
    """
    Monta as transformações aplicadas antes do modelo.

    - Numéricas: preenche faltantes com a mediana e padroniza a escala.
    - Categóricas: preenche faltantes com o valor mais frequente e aplica
      one-hot encoding. `handle_unknown="ignore"` evita que a API quebre
      caso apareça uma categoria nunca vista no treino.
    """
    transformacao_numerica = Pipeline([
        ("imputacao", SimpleImputer(strategy="median")),
        ("escala", StandardScaler()),
    ])

    transformacao_categorica = Pipeline([
        ("imputacao", SimpleImputer(strategy="most_frequent")),
        ("codificacao", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    return ColumnTransformer(
        transformers=[
            ("numericas", transformacao_numerica, list(COLUNAS_NUMERICAS)),
            ("categoricas", transformacao_categorica, list(COLUNAS_CATEGORICAS)),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
