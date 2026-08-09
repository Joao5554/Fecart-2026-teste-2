"""
Gerador de dados SINTÉTICOS de ocorrências de desastres naturais.

ATENÇÃO: estes dados NÃO são reais. Eles existem apenas para o projeto
funcionar de ponta a ponta (treinar, avaliar e servir previsões) enquanto
a base histórica real do Brasil não está disponível.

Os dados são gerados com relações climáticas e geográficas plausíveis
(por exemplo: muita chuva + terreno íngreme aumenta a chance de
deslizamento), de forma que o modelo aprenda padrões coerentes e o
pipeline possa ser validado desde já.

Como executar (a partir da raiz do projeto):
    python treinamento/gerar_dados_exemplo.py

A geração é determinística: com a mesma SEMENTE, o arquivo gerado é
sempre idêntico. Isso mantém o projeto reprodutível para toda a equipe.
"""

import sys
from pathlib import Path

# Permite executar este arquivo diretamente (python treinamento/gerar_dados_exemplo.py)
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from treinamento.esquema import (
    ARQUIVO_DADOS_EXEMPLO,
    COLUNA_ALVO,
    NOMES_COLUNAS,
)

SEMENTE = 42
N_AMOSTRAS = 6000

# Proporção de linhas sem nenhum desastre registrado (classe "nenhum").
PROPORCAO_SEM_DESASTRE = 0.50

# Percentual de rótulos trocados de propósito, imitando a subnotificação e os
# erros de classificação que existem em qualquer base histórica real.
TAXA_RUIDO_ROTULO = 0.08

# Perfil climático e geográfico médio por região.
# (chuva_base_mm, temperatura_c, umidade_pct, altitude_m, declividade_pct)
PERFIL_REGIAO = {
    "Norte": (220.0, 27.0, 82.0, 120.0, 6.0),
    "Nordeste": (70.0, 27.5, 62.0, 300.0, 8.0),
    "Centro-Oeste": (130.0, 25.5, 65.0, 700.0, 7.0),
    "Sudeste": (140.0, 22.5, 72.0, 650.0, 14.0),
    "Sul": (150.0, 19.5, 76.0, 400.0, 11.0),
}

UF_POR_REGIAO = {
    "Norte": ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MS", "MT"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
}

# Biomas mais prováveis em cada região (pesos na mesma ordem).
BIOMA_POR_REGIAO = {
    "Norte": (["Amazonia", "Cerrado"], [0.9, 0.1]),
    "Nordeste": (["Caatinga", "Cerrado", "Mata Atlantica"], [0.6, 0.25, 0.15]),
    "Centro-Oeste": (["Cerrado", "Pantanal", "Amazonia"], [0.75, 0.15, 0.10]),
    "Sudeste": (["Mata Atlantica", "Cerrado"], [0.7, 0.3]),
    "Sul": (["Mata Atlantica", "Pampa"], [0.65, 0.35]),
}

PESO_REGIAO = [0.13, 0.28, 0.12, 0.32, 0.15]


def _fator_sazonal(regiao: str, mes: np.ndarray) -> np.ndarray:
    """
    Multiplicador de chuva conforme o mês.

    No Brasil, o verão (dez-mar) concentra as chuvas na maior parte do país.
    No Nordeste o padrão é deslocado e menos intenso.
    """
    ciclo = np.cos(2 * np.pi * (mes - 1) / 12)  # 1 em janeiro, -1 em julho
    if regiao == "Nordeste":
        return 1.0 + 0.45 * np.cos(2 * np.pi * (mes - 3) / 12)
    if regiao == "Sul":
        return 1.0 + 0.20 * ciclo  # chuva melhor distribuída no ano
    return 1.0 + 0.65 * ciclo


def _sortear_classe(rng: np.random.Generator, dados: pd.DataFrame) -> np.ndarray:
    """
    Define o tipo de desastre a partir das condições de cada linha.

    Cada tipo de desastre recebe uma pontuação de risco calculada a partir
    das variáveis climáticas e geográficas. Vence o tipo com maior pontuação,
    desde que ela ultrapasse um limiar mínimo; caso contrário a linha fica
    como "nenhum". Por fim, uma parcela dos rótulos é trocada de propósito
    para imitar o ruído de uma base histórica real.
    """
    chuva = dados["precipitacao_mm"].to_numpy()
    chuva_24h = dados["precipitacao_max_24h_mm"].to_numpy()
    temp = dados["temperatura_media_c"].to_numpy()
    umidade = dados["umidade_relativa_pct"].to_numpy()
    vento = dados["rajada_vento_max_kmh"].to_numpy()
    declive = dados["declividade_media_pct"].to_numpy()
    densidade = dados["densidade_demografica_hab_km2"].to_numpy()
    urbana = dados["pct_area_urbana"].to_numpy()
    ndvi = dados["indice_vegetacao_ndvi"].to_numpy()
    altitude = dados["altitude_m"].to_numpy()

    def normalizar(v, minimo, maximo):
        return np.clip((v - minimo) / (maximo - minimo), 0, 1)

    seco = normalizar(60 - chuva, 0, 60)
    quente = normalizar(temp - 24, 0, 10)
    ar_seco = normalizar(60 - umidade, 0, 35)

    escore_estiagem = 3.2 * seco + 1.4 * quente + 1.2 * ar_seco

    escore_inundacao = (
        2.6 * normalizar(chuva - 150, 0, 350)
        + 2.4 * normalizar(chuva_24h - 60, 0, 120)
        + 1.1 * normalizar(urbana, 20, 100)
        + 0.9 * normalizar(200 - altitude, 0, 200)
    )

    escore_deslizamento = (
        2.2 * normalizar(chuva - 150, 0, 350)
        + 2.0 * normalizar(chuva_24h - 70, 0, 110)
        + 2.6 * normalizar(declive - 12, 0, 28)
        + 1.0 * normalizar(densidade, 500, 6000)
    )

    escore_tempestade = (
        3.0 * normalizar(vento - 55, 0, 70)
        + 1.3 * normalizar(chuva_24h - 40, 0, 100)
        + 0.7 * quente
    )

    escore_incendio = (
        2.8 * seco
        + 1.6 * ar_seco
        + 1.3 * quente
        + 1.2 * normalizar(0.55 - ndvi, 0, 0.4)
    )

    classes_desastre = np.array([
        "estiagem_seca",
        "inundacao",
        "deslizamento",
        "tempestade",
        "incendio_florestal",
    ])

    escores = np.column_stack([
        escore_estiagem,
        escore_inundacao,
        escore_deslizamento,
        escore_tempestade,
        escore_incendio,
    ])

    # Cada tipo de desastre tem escala própria. Dividir cada coluna pelo seu
    # percentil 92 coloca todas na mesma régua, para que uma classe não
    # domine as outras só por ter números naturalmente maiores.
    escores = escores / np.percentile(escores, 92, axis=0)

    maior_escore = escores.max(axis=1)
    tipo_dominante = classes_desastre[escores.argmax(axis=1)]

    # Só vira desastre quando a condição dominante é forte o bastante.
    # O limiar é um quantil, então a proporção de "nenhum" fica estável
    # independentemente do número de amostras.
    limiar = np.quantile(maior_escore, PROPORCAO_SEM_DESASTRE)
    rotulos = np.where(maior_escore >= limiar, tipo_dominante, "nenhum")

    # Ruído de rótulo: nem todo evento é registrado corretamente na base real
    # (subnotificação, erro de classificação). Sem isso o problema ficaria
    # perfeito demais e o modelo pareceria bom além do razoável.
    todas_classes = np.concatenate([["nenhum"], classes_desastre])
    com_ruido = rng.random(len(dados)) < TAXA_RUIDO_ROTULO
    rotulos[com_ruido] = rng.choice(todas_classes, size=int(com_ruido.sum()))

    return rotulos


def gerar(n_amostras: int = N_AMOSTRAS, semente: int = SEMENTE) -> pd.DataFrame:
    """Gera o DataFrame sintético completo, já com a coluna alvo."""
    rng = np.random.default_rng(semente)

    regioes = rng.choice(list(PERFIL_REGIAO), size=n_amostras, p=PESO_REGIAO)
    mes = rng.integers(1, 13, size=n_amostras)

    ufs = np.empty(n_amostras, dtype=object)
    biomas = np.empty(n_amostras, dtype=object)
    chuva_base = np.zeros(n_amostras)
    temp_base = np.zeros(n_amostras)
    umid_base = np.zeros(n_amostras)
    alt_base = np.zeros(n_amostras)
    decl_base = np.zeros(n_amostras)

    for regiao in PERFIL_REGIAO:
        mascara = regioes == regiao
        n = int(mascara.sum())
        if n == 0:
            continue

        ufs[mascara] = rng.choice(UF_POR_REGIAO[regiao], size=n)
        opcoes_bioma, pesos_bioma = BIOMA_POR_REGIAO[regiao]
        biomas[mascara] = rng.choice(opcoes_bioma, size=n, p=pesos_bioma)

        chuva_reg, temp_reg, umid_reg, alt_reg, decl_reg = PERFIL_REGIAO[regiao]
        sazonal = _fator_sazonal(regiao, mes[mascara])

        chuva_base[mascara] = chuva_reg * sazonal * rng.lognormal(0, 0.45, n)
        temp_base[mascara] = temp_reg + 3.5 * np.cos(
            2 * np.pi * (mes[mascara] - 1) / 12
        ) + rng.normal(0, 1.8, n)
        umid_base[mascara] = umid_reg + rng.normal(0, 7, n)
        alt_base[mascara] = np.abs(rng.normal(alt_reg, alt_reg * 0.6 + 50, n))
        decl_base[mascara] = np.abs(rng.normal(decl_reg, 6, n))

    chuva = np.clip(chuva_base, 0, 1500)
    # A chuva de 24h é uma fração da mensal, maior quando chove poucos dias.
    dias_chuva = np.clip(
        rng.binomial(31, np.clip(chuva / 400, 0.02, 0.85)), 0, 31
    )
    fracao_24h = rng.beta(2, 5, n_amostras) * 0.9 + 0.10
    chuva_24h = np.clip(chuva * fracao_24h, 0, 400)

    umidade = np.clip(umid_base + 12 * np.clip(chuva / 300, 0, 1), 5, 100)
    temperatura = np.clip(temp_base - 2.5 * np.clip(chuva / 400, 0, 1), -5, 45)
    altitude = np.clip(alt_base, 0, 3000)
    declividade = np.clip(decl_base + altitude / 400, 0, 60)

    vento = np.clip(
        rng.gamma(4.5, 8.0, n_amostras) + 0.06 * chuva_24h, 0, 180
    )

    densidade = np.clip(rng.lognormal(3.9, 1.5, n_amostras), 0.5, 15000)
    pct_urbana = np.clip(
        8 + 22 * np.log1p(densidade) / np.log(1000) * rng.uniform(0.5, 1.6, n_amostras),
        0,
        100,
    )
    ndvi = np.clip(
        0.28
        + 0.45 * np.clip(chuva / 250, 0, 1)
        - 0.30 * (pct_urbana / 100)
        + rng.normal(0, 0.07, n_amostras),
        0,
        1,
    )

    dados = pd.DataFrame({
        "uf": ufs,
        "regiao": regioes,
        "bioma": biomas,
        "mes": mes,
        "precipitacao_mm": chuva.round(1),
        "precipitacao_max_24h_mm": chuva_24h.round(1),
        "dias_com_chuva": dias_chuva,
        "temperatura_media_c": temperatura.round(1),
        "umidade_relativa_pct": umidade.round(1),
        "rajada_vento_max_kmh": vento.round(1),
        "altitude_m": altitude.round(0),
        "declividade_media_pct": declividade.round(1),
        "densidade_demografica_hab_km2": densidade.round(1),
        "pct_area_urbana": pct_urbana.round(1),
        "indice_vegetacao_ndvi": ndvi.round(3),
    })

    dados[COLUNA_ALVO] = _sortear_classe(rng, dados)

    # Garante a ordem definida no esquema.
    return dados[list(NOMES_COLUNAS) + [COLUNA_ALVO]]


def main() -> None:
    dados = gerar()
    ARQUIVO_DADOS_EXEMPLO.parent.mkdir(parents=True, exist_ok=True)
    dados.to_csv(ARQUIVO_DADOS_EXEMPLO, index=False, encoding="utf-8")

    print(f"Dados sintéticos gerados: {len(dados)} linhas")
    print(f"Arquivo: {ARQUIVO_DADOS_EXEMPLO}")
    print("\nDistribuição das classes:")
    contagem = dados[COLUNA_ALVO].value_counts()
    for classe, quantidade in contagem.items():
        print(f"  {classe:<20} {quantidade:>5}  ({quantidade / len(dados):.1%})")


if __name__ == "__main__":
    main()
