"""
Gerador de dados SINTÉTICOS para desenvolvimento.

ATENÇÃO: estes dados são INVENTADOS. Servem só para testar se o pipeline
funciona de ponta a ponta — treino, avaliação, salvamento e API — enquanto a
base real do S2iD não está disponível. Nenhum resultado obtido com eles vale
como previsão de verdade, e nenhum número daqui deve ir para a apresentação.

O que ele faz de útil:
  - Escreve um CSV no formato EXATO definido em src/esquema.py, então o dia em
    que a base real entrar, nada no código precisa mudar.
  - As relações entre as variáveis são plausíveis (chuva concentrada + encosta
    íngreme + histórico de ocorrência => risco maior), com bastante ruído.
    O ruído é proposital: sem ele o modelo acertaria 100% e a avaliação não
    diria nada sobre a qualidade do pipeline.

Como usar:
    python dados/gerar_dados_sinteticos.py
    python dados/gerar_dados_sinteticos.py --anos 2018 2024 --saida dados/teste.csv
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import esquema, procedencia  # noqa: E402


# --------------------------------------------------------------------------
# Municípios de referência
# --------------------------------------------------------------------------
# Códigos IBGE e localizações são reais; população, área, altitude e
# declividade são aproximações grosseiras. A escolha privilegia municípios com
# histórico conhecido de desastres, para o dataset ter variedade.
#
# (codigo_ibge, municipio, uf, regiao, bioma, lat, lon,
#  area_km2, populacao, altitude_m, declividade_graus)

MUNICIPIOS = [
    (3303906, "Petropolis", "RJ", "Sudeste", "Mata Atlantica", -22.51, -43.18, 796, 307_144, 809, 24.0),
    (3548906, "Sao Sebastiao", "SP", "Sudeste", "Mata Atlantica", -23.76, -45.41, 400, 87_000, 20, 21.0),
    (3304557, "Rio de Janeiro", "RJ", "Sudeste", "Mata Atlantica", -22.91, -43.20, 1_200, 6_211_000, 10, 12.0),
    (3550308, "Sao Paulo", "SP", "Sudeste", "Mata Atlantica", -23.55, -46.63, 1_521, 11_451_000, 760, 7.0),
    (3106200, "Belo Horizonte", "MG", "Sudeste", "Mata Atlantica", -19.92, -43.94, 331, 2_315_000, 852, 11.0),
    (3205309, "Vitoria", "ES", "Sudeste", "Mata Atlantica", -20.32, -40.34, 97, 365_000, 12, 8.0),
    (3169307, "Teofilo Otoni", "MG", "Sudeste", "Mata Atlantica", -17.86, -41.51, 3_242, 141_000, 349, 14.0),
    (3136702, "Juiz de Fora", "MG", "Sudeste", "Mata Atlantica", -21.76, -43.35, 1_436, 540_000, 678, 13.0),
    (3552205, "Sorocaba", "SP", "Sudeste", "Mata Atlantica", -23.50, -47.46, 449, 723_000, 601, 6.0),
    (3547809, "Santo Andre", "SP", "Sudeste", "Mata Atlantica", -23.66, -46.53, 175, 748_000, 796, 10.0),

    (4202404, "Blumenau", "SC", "Sul", "Mata Atlantica", -26.92, -49.07, 519, 361_000, 21, 16.0),
    (4209102, "Joinville", "SC", "Sul", "Mata Atlantica", -26.30, -48.85, 1_127, 616_000, 4, 9.0),
    (4314902, "Porto Alegre", "RS", "Sul", "Pampa", -30.03, -51.23, 496, 1_332_000, 10, 5.0),
    (4305108, "Caxias do Sul", "RS", "Sul", "Mata Atlantica", -29.17, -51.18, 1_652, 517_000, 817, 12.0),
    (4106902, "Curitiba", "PR", "Sul", "Mata Atlantica", -25.43, -49.27, 435, 1_773_000, 934, 5.0),
    (4115200, "Maringa", "PR", "Sul", "Mata Atlantica", -23.42, -51.94, 487, 430_000, 515, 4.0),
    (4314548, "Muçum", "RS", "Sul", "Mata Atlantica", -29.16, -51.87, 111, 4_800, 90, 15.0),
    (4318705, "Santa Maria", "RS", "Sul", "Pampa", -29.68, -53.81, 1_788, 283_000, 113, 7.0),

    (2611606, "Recife", "PE", "Nordeste", "Mata Atlantica", -8.05, -34.88, 218, 1_661_000, 4, 9.0),
    (2704302, "Maceio", "AL", "Nordeste", "Mata Atlantica", -9.66, -35.73, 511, 957_000, 7, 8.0),
    (2927408, "Salvador", "BA", "Nordeste", "Mata Atlantica", -12.97, -38.50, 693, 2_418_000, 8, 10.0),
    (2304400, "Fortaleza", "CE", "Nordeste", "Caatinga", -3.72, -38.54, 313, 2_428_000, 21, 3.0),
    (2408102, "Natal", "RN", "Nordeste", "Caatinga", -5.79, -35.21, 167, 751_000, 30, 4.0),
    (2507507, "Joao Pessoa", "PB", "Nordeste", "Mata Atlantica", -7.12, -34.86, 211, 833_000, 47, 5.0),
    (2910800, "Feira de Santana", "BA", "Nordeste", "Caatinga", -12.27, -38.97, 1_338, 616_000, 234, 4.0),
    (2211001, "Teresina", "PI", "Nordeste", "Caatinga", -5.09, -42.80, 1_392, 866_000, 72, 3.0),
    (2507200, "Patos", "PB", "Nordeste", "Caatinga", -7.02, -37.28, 473, 108_000, 249, 5.0),
    (2603454, "Caruaru", "PE", "Nordeste", "Caatinga", -8.28, -35.98, 921, 365_000, 554, 8.0),
    (2111300, "Sao Luis", "MA", "Nordeste", "Amazonia", -2.53, -44.30, 583, 1_037_000, 24, 4.0),

    (1302603, "Manaus", "AM", "Norte", "Amazonia", -3.12, -60.02, 11_401, 2_063_000, 92, 4.0),
    (1501402, "Belem", "PA", "Norte", "Amazonia", -1.46, -48.50, 1_059, 1_303_000, 10, 3.0),
    (1200401, "Rio Branco", "AC", "Norte", "Amazonia", -9.97, -67.81, 8_836, 364_000, 153, 3.0),
    (1100205, "Porto Velho", "RO", "Norte", "Amazonia", -8.76, -63.90, 34_090, 460_000, 85, 3.0),
    (1600303, "Macapa", "AP", "Norte", "Amazonia", 0.03, -51.07, 6_563, 512_000, 17, 2.0),
    (1721000, "Palmas", "TO", "Norte", "Cerrado", -10.18, -48.33, 2_219, 313_000, 230, 5.0),

    (5300108, "Brasilia", "DF", "Centro-Oeste", "Cerrado", -15.78, -47.93, 5_760, 2_817_000, 1_100, 6.0),
    (5208707, "Goiania", "GO", "Centro-Oeste", "Cerrado", -16.68, -49.25, 729, 1_437_000, 749, 5.0),
    (5103403, "Cuiaba", "MT", "Centro-Oeste", "Cerrado", -15.60, -56.10, 3_293, 650_000, 165, 4.0),
    (5002704, "Campo Grande", "MS", "Centro-Oeste", "Cerrado", -20.44, -54.65, 8_092, 897_000, 592, 4.0),
    (5003207, "Corumba", "MS", "Centro-Oeste", "Pantanal", -19.01, -57.65, 64_960, 112_000, 118, 3.0),
]


# Chuva média por mês (mm), por região. Aproxima o regime sazonal brasileiro:
# verão chuvoso no Centro-Sul, inverno seco, e Sul mais uniforme o ano todo.
CHUVA_MENSAL = {
    "Norte":        [320, 335, 350, 310, 240, 145, 105, 85, 110, 175, 225, 285],
    "Nordeste":     [110, 135, 165, 145, 95, 60, 45, 25, 20, 35, 55, 85],
    "Centro-Oeste": [255, 220, 200, 115, 50, 18, 12, 20, 55, 135, 200, 270],
    "Sudeste":      [235, 190, 170, 80, 50, 30, 25, 28, 62, 120, 180, 225],
    "Sul":          [160, 150, 145, 130, 120, 130, 128, 140, 165, 175, 140, 155],
}


def grupos_aplicaveis(municipio: tuple) -> list[str]:
    """Escolhe quais tipos de desastre fazem sentido para o município.

    Não adianta gerar linhas de seca para Manaus nem de deslizamento para uma
    cidade plana — na base real do S2iD esses registros também não existiriam.
    """
    _, _, _, regiao, bioma, _, _, _, _, _, declividade = municipio
    grupos = ["INUNDACAO", "ALAGAMENTO", "EROSAO"]

    if declividade >= 8:
        grupos.append("DESLIZAMENTO")
    if declividade >= 6:
        grupos.append("ENXURRADA")
    if bioma in ("Caatinga", "Cerrado", "Pampa"):
        grupos.append("ESTIAGEM_SECA")
    if regiao in ("Sul", "Sudeste"):
        grupos.append("VENDAVAL_CICLONE")
    if regiao in ("Sul", "Sudeste", "Centro-Oeste"):
        grupos.append("GRANIZO")
    if bioma in ("Cerrado", "Amazonia", "Pantanal"):
        grupos.append("INCENDIO_FLORESTAL")

    return grupos


def calcular_score(linha: dict, rng: np.random.Generator) -> float:
    """Calcula um 'risco latente' a partir das features.

    É a regra que o modelo vai tentar redescobrir sozinho. De propósito ela
    combina várias variáveis de formas diferentes por tipo de desastre — é o
    que torna a tarefa não-trivial e o teste do pipeline significativo.
    """
    grupo = linha["cobrade_grupo"]
    score = 0.0

    # Histórico pesa em todos os tipos: onde já aconteceu, tende a repetir.
    score += 0.45 * min(linha["ocorrencias_12m"], 6)
    score += 0.05 * min(linha["ocorrencias_total_historico"], 40)
    score += 0.30 * linha["decretos_emergencia_5anos"]
    if linha["meses_desde_ultima_ocorrencia"] < 12:
        score += 1.2

    # Exposição da população
    score += 0.05 * linha["percentual_domicilios_area_risco"]
    score += 0.6 * np.log10(max(linha["populacao"], 1_000) / 1_000)

    if grupo in ("INUNDACAO", "ENXURRADA", "ALAGAMENTO"):
        # Volume total importa, mas concentração importa mais.
        score += 0.014 * linha["chuva_acumulada_mm"]
        score += 0.045 * linha["chuva_max_24h_mm"]
        score += 0.020 * linha["chuva_max_72h_mm"]
        score += 0.012 * linha["anomalia_chuva_percentual"]
        score += 0.035 * linha["umidade_solo_percentual"]   # solo saturado não absorve
        score += 2.5 / (1.0 + linha["distancia_curso_agua_km"])
        score += 0.04 * linha["percentual_area_urbana"]      # asfalto não infiltra
        if grupo == "ENXURRADA":
            score += 0.10 * linha["declividade_media_graus"]

    elif grupo == "DESLIZAMENTO":
        # Encosta íngreme + chuva encharcando o solo + pouca vegetação segurando.
        score += 0.16 * linha["declividade_media_graus"]
        score += 0.055 * linha["chuva_max_72h_mm"]
        score += 0.030 * linha["chuva_max_24h_mm"]
        score += 0.045 * linha["umidade_solo_percentual"]
        score -= 3.0 * linha["indice_vegetacao"]             # raiz segura o barranco
        score += 0.06 * linha["percentual_domicilios_area_risco"]

    elif grupo == "ESTIAGEM_SECA":
        # Aqui a lógica se inverte: chuva de menos é o problema.
        score -= 0.020 * linha["chuva_acumulada_mm"]
        score -= 0.025 * linha["anomalia_chuva_percentual"]
        score += 0.10 * linha["temperatura_media_c"]
        score -= 0.05 * linha["umidade_relativa_media"]
        score += 4.0 if linha["dias_com_chuva"] <= 2 else 0.0

    elif grupo == "INCENDIO_FLORESTAL":
        score -= 0.015 * linha["chuva_acumulada_mm"]
        score += 0.14 * linha["temperatura_max_c"]
        score -= 0.06 * linha["umidade_relativa_media"]
        score += 2.0 * linha["indice_vegetacao"]             # precisa ter o que queimar
        score += 0.02 * linha["velocidade_vento_max_kmh"]

    elif grupo in ("VENDAVAL_CICLONE", "GRANIZO"):
        score += 0.055 * linha["velocidade_vento_max_kmh"]
        score += 0.020 * linha["chuva_max_24h_mm"]
        score += 0.05 * linha["temperatura_max_c"]

    elif grupo == "EROSAO":
        score += 0.09 * linha["declividade_media_graus"]
        score += 0.012 * linha["chuva_acumulada_mm"]
        score -= 2.0 * linha["indice_vegetacao"]

    # Ruído: representa tudo que a base não mede (obra de contenção feita no
    # ano passado, drenagem entupida, sorte). Sem isso o modelo acertaria 100%
    # e a avaliação não testaria nada.
    score += rng.normal(0, 2.6)

    return score


def gerar(ano_inicial: int, ano_final: int, semente: int) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    linhas = []

    for mun in MUNICIPIOS:
        (codigo, nome, uf, regiao, bioma, lat, lon,
         area, populacao, altitude, declividade) = mun

        # --- características fixas do município ---
        densidade = populacao / area
        percentual_urbano = float(np.clip(
            35 + 22 * np.log10(max(densidade, 1)) + rng.normal(0, 8), 5, 100
        ))
        percentual_risco = float(np.clip(
            0.35 * declividade + 0.004 * np.sqrt(populacao) + rng.normal(0, 3), 0, 45
        ))
        vegetacao = float(np.clip(
            0.75 - 0.004 * percentual_urbano + rng.normal(0, 0.08), 0.05, 0.95
        ))
        distancia_agua = float(np.clip(rng.gamma(2.0, 1.6), 0.05, 40))

        grupos = grupos_aplicaveis(mun)

        # Propensão de cada grupo neste município. Cria municípios "problema"
        # para certos desastres, como acontece na realidade.
        propensao = {g: float(rng.uniform(0.2, 2.0)) for g in grupos}

        # Histórico acumulado, atualizado mês a mês ao longo da simulação.
        historico_total = {g: int(rng.poisson(3 * propensao[g])) for g in grupos}
        meses_desde = {g: int(rng.integers(1, 60)) if historico_total[g] > 0 else 999
                       for g in grupos}
        ocorrencias_recentes = {g: [] for g in grupos}
        decretos = {g: int(rng.poisson(0.6 * propensao[g])) for g in grupos}

        for ano in range(ano_inicial, ano_final + 1):
            for mes in range(1, 13):
                # --- clima do mês ---
                media_chuva = CHUVA_MENSAL[regiao][mes - 1]
                # Fator de ano: simula El Niño / La Niña, afetando o ano inteiro.
                fator_ano = 1.0 + 0.22 * np.sin(ano * 1.7 + hash(regiao) % 7)
                chuva = float(max(0.0, rng.gamma(
                    shape=2.2, scale=media_chuva * fator_ano / 2.2
                )))

                dias_chuva = int(np.clip(
                    rng.binomial(31, min(0.95, chuva / 320 + 0.05)), 0, 31
                ))
                # A chuva de 24h é uma fração da mensal; caudas longas geram os
                # eventos extremos que causam os desastres de verdade.
                fracao_24h = float(np.clip(rng.beta(1.7, 5.0), 0.02, 0.85))
                chuva_24h = float(min(chuva * fracao_24h, 580))
                chuva_72h = float(min(chuva_24h * rng.uniform(1.0, 1.9), 980))

                anomalia = float(np.clip(
                    100 * (chuva - media_chuva) / max(media_chuva, 1), -100, 480
                ))

                temp_base = {"Norte": 27, "Nordeste": 26, "Centro-Oeste": 24,
                             "Sudeste": 21, "Sul": 18}[regiao]
                sazonal = -3.5 * np.cos(2 * np.pi * (mes - 1) / 12)
                if lat < -15:  # hemisfério mais ao sul: inverno em jun-ago
                    sazonal = 3.5 * np.cos(2 * np.pi * (mes - 1) / 12)
                temp_media = float(np.clip(
                    temp_base + sazonal - 0.004 * altitude + rng.normal(0, 1.5), -2, 42
                ))
                temp_max = float(np.clip(
                    temp_media + rng.uniform(5, 12), 0, 48
                ))
                umidade_ar = float(np.clip(
                    52 + 0.10 * chuva + rng.normal(0, 7), 15, 100
                ))
                umidade_solo = float(np.clip(
                    28 + 0.13 * chuva + rng.normal(0, 9), 3, 100
                ))
                vento = float(np.clip(rng.gamma(3.0, 8.0), 3, 190))

                # Nem todo município tem estação fluviométrica da ANA.
                tem_estacao = distancia_agua < 12
                nivel_rio = (
                    float(np.clip(1.4 + 0.011 * chuva + rng.normal(0, 0.7), 0, 45))
                    if tem_estacao else np.nan
                )
                # Falha de coleta acontece: ~6% dos meses sem dado de solo.
                if rng.random() < 0.06:
                    umidade_solo_registrada = np.nan
                else:
                    umidade_solo_registrada = umidade_solo

                for grupo in grupos:
                    recentes = [m for m in ocorrencias_recentes[grupo]
                                if (ano * 12 + mes) - m <= 12]
                    ocorrencias_recentes[grupo] = recentes

                    linha = {
                        "codigo_ibge": codigo,
                        "municipio": nome,
                        "uf": uf,
                        "regiao": regiao,
                        "bioma": bioma,
                        "ano": ano,
                        "mes": mes,
                        "cobrade_grupo": grupo,

                        "latitude": lat,
                        "longitude": lon,
                        "area_km2": float(area),
                        "populacao": float(populacao),
                        "densidade_demografica": round(densidade, 2),
                        "altitude_media_m": float(altitude),
                        "declividade_media_graus": declividade,
                        "percentual_area_urbana": round(percentual_urbano, 1),
                        "percentual_domicilios_area_risco": round(percentual_risco, 1),
                        "indice_vegetacao": round(vegetacao, 3),
                        "distancia_curso_agua_km": round(distancia_agua, 2),

                        "chuva_acumulada_mm": round(chuva, 1),
                        "chuva_max_24h_mm": round(chuva_24h, 1),
                        "chuva_max_72h_mm": round(chuva_72h, 1),
                        "dias_com_chuva": dias_chuva,
                        "anomalia_chuva_percentual": round(anomalia, 1),
                        "temperatura_media_c": round(temp_media, 1),
                        "temperatura_max_c": round(temp_max, 1),
                        "umidade_relativa_media": round(umidade_ar, 1),
                        "umidade_solo_percentual": (
                            round(umidade_solo_registrada, 1)
                            if not np.isnan(umidade_solo_registrada) else np.nan
                        ),
                        "nivel_rio_m": (
                            round(nivel_rio, 2) if not np.isnan(nivel_rio) else np.nan
                        ),
                        "velocidade_vento_max_kmh": round(vento, 1),

                        "ocorrencias_12m": len(recentes),
                        "ocorrencias_total_historico": historico_total[grupo],
                        "meses_desde_ultima_ocorrencia": meses_desde[grupo],
                        "decretos_emergencia_5anos": decretos[grupo],
                        "media_afetados_historico": round(
                            historico_total[grupo] * populacao * 0.0012, 1
                        ),
                        "danos_materiais_historico_reais": round(
                            historico_total[grupo] * populacao * 4.5, 2
                        ),
                    }

                    # O score usa a umidade real do solo, não a registrada:
                    # o fenômeno acontece mesmo quando o sensor falha. É assim
                    # que dado faltante vira ruído de verdade para o modelo.
                    linha_score = dict(linha)
                    linha_score["umidade_solo_percentual"] = umidade_solo
                    score = calcular_score(linha_score, rng) * propensao[grupo]

                    linha["_score"] = score
                    linhas.append(linha)

                    # Atualiza o histórico para os meses seguintes.
                    if score > 9.0:
                        ocorrencias_recentes[grupo].append(ano * 12 + mes)
                        historico_total[grupo] += 1
                        meses_desde[grupo] = 0
                        if score > 13.0 and rng.random() < 0.4:
                            decretos[grupo] += 1
                    else:
                        meses_desde[grupo] = min(
                            meses_desde[grupo] + 1
                            if meses_desde[grupo] < 999 else 999,
                            999,
                        )

    dados = pd.DataFrame(linhas)

    # Converte o score contínuo em baixo / medio / alto.
    # Os cortes são por tipo de desastre, porque as escalas de score diferem
    # entre eles — e porque na prática cada tipo tem seu próprio critério.
    dados[esquema.COLUNA_ALVO] = ""
    for grupo, bloco in dados.groupby("cobrade_grupo"):
        cortes = bloco["_score"].quantile([0.62, 0.88])
        dados.loc[bloco.index, esquema.COLUNA_ALVO] = pd.cut(
            bloco["_score"],
            bins=[-np.inf, cortes.iloc[0], cortes.iloc[1], np.inf],
            labels=esquema.CLASSES_RISCO,
        ).astype(str)

    dados = dados.drop(columns=["_score"])

    # Embaralha para o CSV não ficar ordenado por município.
    dados = dados.sample(frac=1.0, random_state=semente).reset_index(drop=True)

    return dados[esquema.COLUNAS_OBRIGATORIAS]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera um CSV sintético no formato do projeto."
    )
    parser.add_argument("--anos", nargs=2, type=int, default=[2015, 2024],
                        metavar=("INICIO", "FIM"),
                        help="intervalo de anos a simular (padrão: 2015 2024)")
    parser.add_argument("--saida", type=Path,
                        default=Path(__file__).parent / "dados.csv",
                        help="caminho do CSV de saída")
    parser.add_argument("--semente", type=int, default=42,
                        help="semente aleatória, para o resultado ser reproduzível")
    args = parser.parse_args()

    print("Gerando dados sintéticos...")
    print(f"  Municípios: {len(MUNICIPIOS)}")
    print(f"  Período:    {args.anos[0]} a {args.anos[1]}")

    dados = gerar(args.anos[0], args.anos[1], args.semente)

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    dados.to_csv(args.saida, index=False, encoding="utf-8")

    # Marca o arquivo como sintético. É assim que o treinamento e a API sabem
    # avisar que os resultados não valem como conclusão sobre desastres reais.
    registro = procedencia.registrar_sintetico(
        args.saida, args.semente, (args.anos[0], args.anos[1]), len(dados)
    )

    print(f"\n{len(dados):,} linhas escritas em {args.saida}")
    print(f"Procedência registrada em {registro.name} (marcado como sintético)")
    print("\nDistribuição do nível de risco:")
    contagem = dados[esquema.COLUNA_ALVO].value_counts()
    for classe in esquema.CLASSES_RISCO:
        n = int(contagem.get(classe, 0))
        print(f"  {classe:<8} {n:>7,}  ({n / len(dados):.1%})")

    print("\nLinhas por tipo de desastre:")
    for grupo, n in dados["cobrade_grupo"].value_counts().items():
        print(f"  {grupo:<20} {n:>7,}")

    print("\nLembre-se: estes dados são inventados. Use apenas para testar o "
          "pipeline.")


if __name__ == "__main__":
    main()
