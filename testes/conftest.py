"""
Configuração e dados compartilhados pelos testes.

Os testes NÃO dependem do arquivo bruto do Atlas (que tem 82 MB e não vai
para o Git). Em vez disso, fabricam um punhado de ocorrências no mesmo
formato que `atlas.carregar_atlas` devolve e passam pelo ETL de verdade.
Assim o código realmente exercitado é o mesmo que roda em produção.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import atlas  # noqa: E402


def _ocorrencia(ibge, municipio, uf, regiao, grupo, ano, mes,
                reconhecido=False, mortos=0, afetados=100, prejuizo=1000.0):
    return {
        "codigo_ibge": ibge, "municipio": municipio, "uf": uf, "regiao": regiao,
        "ano": ano, "mes": mes, "grupo_desastre": grupo,
        "reconhecido": reconhecido, "mortos": mortos,
        "afetados": afetados, "prejuizo": prejuizo,
    }


@pytest.fixture(scope="session")
def ocorrencias():
    """
    Ocorrências fabricadas, no formato de saída de `atlas.carregar_atlas`.

    Três municípios com padrões diferentes de propósito:
      - Petrópolis: deslizamentos graves e recorrentes, sempre no verão;
      - Quixadá: secas longas, com reconhecimento federal;
      - Blumenau: inundações espaçadas, sem mortos.
    """
    linhas = []

    for ano in range(2012, 2026):
        # Deslizamento em Petrópolis, sempre em fevereiro e março.
        linhas.append(_ocorrencia(3303906, "Petropolis", "RJ", "Sudeste",
                                  "DESLIZAMENTO", ano, 2,
                                  reconhecido=True, mortos=3, afetados=5000,
                                  prejuizo=2_000_000.0))
        if ano % 2 == 0:
            linhas.append(_ocorrencia(3303906, "Petropolis", "RJ", "Sudeste",
                                      "DESLIZAMENTO", ano, 3, afetados=800))

        # Seca no Ceará, meses secos do segundo semestre.
        for mes in (8, 9, 10):
            linhas.append(_ocorrencia(2311306, "Quixada", "CE", "Nordeste",
                                      "ESTIAGEM_SECA", ano, mes,
                                      reconhecido=(mes == 9), afetados=20_000,
                                      prejuizo=500_000.0))

        # Inundação em Blumenau a cada dois anos, sem mortos.
        if ano % 2 == 1:
            linhas.append(_ocorrencia(4202404, "Blumenau", "SC", "Sul",
                                      "INUNDACAO", ano, 11, afetados=12_000,
                                      prejuizo=8_000_000.0))

    return pd.DataFrame(linhas)


@pytest.fixture(scope="session")
def dados_exemplo(ocorrencias):
    """Dataset pequeno, produzido pelo ETL real a partir das ocorrências."""
    return atlas.construir_dataset(
        ocorrencias, ano_inicial=2015, ano_final=2025,
        negativos_por_positivo=2, semente=7,
    )


@pytest.fixture
def linha_exemplo(dados_exemplo):
    """Uma única linha, como dicionário — base para os testes da API."""
    return dados_exemplo.iloc[0].to_dict()
