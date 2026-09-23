"""
Prepara a base de temperatura do projeto, a partir dos dados do INMET.

Como executar (a partir da raiz do projeto):
    python dados/preparar_temperatura.py

O que faz:
    1. Baixa de portal.inmet.gov.br os anos que ainda não estiverem em
       dados/bruto/inmet/ (um ZIP por ano, de 60 a 90 MB cada)
    2. Lê a temperatura horária de cada estação automática
    3. Reduz tudo a uma linha por estação, ano e mês
    4. Escreve dados/temperatura_estacoes.csv

Por que ano E mês, e não só o mês
---------------------------------
A camada de vento guarda só doze linhas por estação, porque direção de vento
não tem sentido fora de um mês: a predominante de janeiro e a de julho podem
ser opostas, e a média das duas não descreve nenhuma das duas.

Temperatura não tem esse problema — ela é uma média, e média de médias
continua significando alguma coisa. Guardando ano e mês, o mesmo arquivo
responde às três perguntas que os mapas fazem:

    mês, sem ano   → o janeiro TÍPICO, apurado sobre todos os anos baixados.
                     É o que os mapas de previsão pedem, porque eles preveem
                     um mês que ainda não aconteceu.
    ano, sem mês   → a média do ano inteiro. É o que o mapa do histórico pede.
    ano e mês      → aquele mês daquele ano, exatamente.

O agrupamento sai barato (são ~600 estações × 12 meses × 5 anos) e o arquivo
fica em menos de 3 MB, então vale mais guardar o detalhe e reduzir na API do
que guardar reduzido e nunca mais poder abrir.

Média, máxima e mínima
----------------------
As três são gravadas. A "máxima" de um mês é a MÉDIA das máximas diárias, não
o pico absoluto — é a definição climatológica, e é a única robusta: o pico
absoluto é um único registro, e um sensor com uma leitura maluca viraria "a
máxima do mês". A média de trinta máximas diárias absorve o erro de uma delas.

A conta está em `src/inmet.py`, na `agregar_mensal`.

O que esta base NÃO é
---------------------
Não é previsão do tempo. É o que os termômetros mediram entre 2021 e 2025,
reduzido a médias mensais. O Windy mostra a temperatura das próximas horas,
saída de um modelo global (GFS/ECMWF) rodado quatro vezes por dia; nada disso
cabe num projeto que roda offline e de propósito não usa internet.

A pergunta que esta base responde é a mesma que o resto do projeto faz: o
risco é estimado para um MÊS, e a temperatura que interessa a esse risco é a
que aquele mês costuma trazer.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import inmet  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PASTA_BRUTO = RAIZ / "dados" / "bruto" / "inmet"
SAIDA = RAIZ / "dados" / "temperatura_estacoes.csv"

# O download é idêntico ao da camada de vento — mesmos ZIPs, mesmo portal.
# Reaproveitar a função evita duas cópias da mesma lógica de rede, e faz com
# que rodar um script depois do outro não baixe nada de novo.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparar_vento import baixar_ano  # noqa: E402

PRIMEIRO_ANO = 2021
ULTIMO_ANO = 2025

# Abaixo disso o mês da estação foi medido por tão poucas horas que a média
# mensal não representa o mês. 240 horas são dez dias de medição contínua —
# o mesmo corte usado pela camada de vento, pelo mesmo motivo.
MINIMO_HORAS_NO_MES = 240

# Faixa fisicamente possível no Brasil, com folga larga dos dois lados. O
# recorde nacional de frio é -14 °C (Urupema/SC) e o de calor 44,8 °C
# (Araçuaí/MG); o que este corte pega é sensor quebrado gravando 60 °C ou
# -40 °C, que existe nos arquivos e envenenaria a média do mês inteiro.
TEMPERATURA_MINIMA_PLAUSIVEL = -25.0
TEMPERATURA_MAXIMA_PLAUSIVEL = 55.0


def montar(mensal: pd.DataFrame) -> pd.DataFrame:
    """
    Reduz o mensal do INMET a uma linha por estação, ano e mês.

    A ordem das três etapas importa, e é esta:

    1. **Descartar sensor com defeito**, linha a linha. É a única que tem de
       vir antes de tudo: uma leitura de 60 °C contamina qualquer média de
       que participe.
    2. **Agrupar**, somando as horas e fazendo a média ponderada por elas.
    3. **Só então cortar o mês mal medido.**

    Cortar antes de agrupar seria o erro sutil: o mesmo mês da mesma estação
    aparece em duas linhas sempre que o ano foi baixado solto E dentro de um
    ZIP, e duas metades de 150 horas seriam jogadas fora separadamente —
    quando juntas fazem um mês de 300 horas, bem medido.
    """
    com_temperatura = mensal.copy()

    if com_temperatura.empty or "temperatura_horas" not in com_temperatura:
        raise SystemExit(
            "Nenhuma medição de temperatura nos arquivos lidos. "
            "Os arquivos baixados têm coluna de temperatura?"
        )

    com_temperatura = com_temperatura[
        com_temperatura["temperatura_horas"].fillna(0) > 0
    ]

    plausivel = com_temperatura["temperatura_media_c"].between(
        TEMPERATURA_MINIMA_PLAUSIVEL, TEMPERATURA_MAXIMA_PLAUSIVEL
    )
    descartadas = int((~plausivel).sum())
    if descartadas:
        print(f"  {descartadas} linhas fora de "
              f"{TEMPERATURA_MINIMA_PLAUSIVEL}..{TEMPERATURA_MAXIMA_PLAUSIVEL} °C "
              "descartadas (sensor com defeito)")
    com_temperatura = com_temperatura[plausivel]
    if com_temperatura.empty:
        raise SystemExit("Nenhuma medição de temperatura plausível nos arquivos.")

    # A média ponderada pelas horas é a que corresponde a juntar as medições:
    # 700 horas a 30 °C e 100 horas a 20 °C dão 28,75 °C, não 25.
    com_temperatura["peso"] = com_temperatura["temperatura_horas"]
    for coluna in ("temperatura_media_c", "temperatura_max_c", "temperatura_min_c"):
        com_temperatura[coluna] = com_temperatura[coluna] * com_temperatura["peso"]

    agrupado = com_temperatura.groupby(
        ["codigo_estacao", "estacao", "uf", "ano", "mes"], as_index=False
    ).agg(
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        altitude=("altitude", "first"),
        temperatura_media_c=("temperatura_media_c", "sum"),
        temperatura_max_c=("temperatura_max_c", "sum"),
        temperatura_min_c=("temperatura_min_c", "sum"),
        peso=("peso", "sum"),
    )

    for coluna in ("temperatura_media_c", "temperatura_max_c", "temperatura_min_c"):
        agrupado[coluna] = agrupado[coluna] / agrupado["peso"]

    agrupado["horas_medidas"] = agrupado["peso"].round().astype(int)

    # Agora sim o corte: sobre as horas SOMADAS do mês, não sobre as de cada
    # arquivo. Abaixo de 240 horas — dez dias de medição contínua — a média
    # não descreve o mês, e é o mesmo corte da camada de vento.
    antes = len(agrupado)
    agrupado = agrupado[agrupado["horas_medidas"] >= MINIMO_HORAS_NO_MES]
    if agrupado.empty:
        raise SystemExit(
            f"Nenhum mês com ao menos {MINIMO_HORAS_NO_MES} horas de "
            "temperatura medidas."
        )
    if antes - len(agrupado):
        print(f"  {antes - len(agrupado)} meses com menos de "
              f"{MINIMO_HORAS_NO_MES} horas descartados (estação fora do ar)")

    # Estação sem coordenada não pode ser desenhada, e o mapa é o único
    # consumidor desta base. Some aqui, e não no navegador.
    agrupado = agrupado[
        agrupado["latitude"].notna() & agrupado["longitude"].notna()
    ]

    colunas = ["codigo_estacao", "estacao", "uf", "ano", "mes",
               "latitude", "longitude", "altitude",
               "temperatura_media_c", "temperatura_max_c", "temperatura_min_c",
               "horas_medidas"]
    saida = agrupado[colunas].sort_values(["codigo_estacao", "ano", "mes"])

    for coluna in ("temperatura_media_c", "temperatura_max_c", "temperatura_min_c"):
        saida[coluna] = saida[coluna].round(2)
    saida["altitude"] = saida["altitude"].round(1)

    return saida


def main() -> None:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--de", type=int, default=PRIMEIRO_ANO)
    analisador.add_argument("--ate", type=int, default=ULTIMO_ANO)
    analisador.add_argument("--sem-baixar", action="store_true",
                            help="usa só o que já está em dados/bruto/inmet/")
    opcoes = analisador.parse_args()

    PASTA_BRUTO.mkdir(parents=True, exist_ok=True)

    if not opcoes.sem_baixar:
        print(f"Baixando o INMET de {opcoes.de} a {opcoes.ate}:")
        baixados = sum(
            baixar_ano(ano, PASTA_BRUTO / f"{ano}.zip")
            for ano in range(opcoes.de, opcoes.ate + 1)
        )
        if not baixados:
            raise SystemExit(
                "Nenhum ano baixou. Sem internet, ou o portal do INMET mudou "
                "de endereço — veja URL_ANO em dados/preparar_vento.py."
            )

    print("Lendo as estações...")
    mensal = inmet.carregar_pasta(PASTA_BRUTO)
    if mensal.empty:
        raise SystemExit(f"Nada para ler em {PASTA_BRUTO}.")

    saida = montar(mensal)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    saida.to_csv(SAIDA, index=False, encoding="utf-8")

    estacoes = saida["codigo_estacao"].nunique()
    print(f"\n{SAIDA.relative_to(RAIZ)}: {len(saida)} linhas, "
          f"{estacoes} estações, "
          f"{saida['ano'].min()}–{saida['ano'].max()}")
    print(f"temperatura média {saida['temperatura_media_c'].mean():.1f} °C "
          f"(de {saida['temperatura_media_c'].min():.1f} "
          f"a {saida['temperatura_media_c'].max():.1f})")


if __name__ == "__main__":
    main()
