"""
Prepara a base de vento do projeto, a partir dos dados do INMET.

Como executar (a partir da raiz do projeto):
    python dados/preparar_vento.py

O que faz:
    1. Baixa de portal.inmet.gov.br os anos que ainda não estiverem em
       dados/bruto/inmet/ (um ZIP por ano, de 60 a 90 MB cada)
    2. Lê a direção e a velocidade horárias de cada estação automática
    3. Reduz tudo a uma linha por estação e mês: o vento predominante
    4. Escreve dados/vento_estacoes.csv

O que a base é, e o que ela não é
---------------------------------
É uma CLIMATOLOGIA MENSAL: o vento como ele costuma soprar em cada mês, em
cada estação, medido ao longo dos anos baixados. Perguntar "março" devolve o
março típico, e não o março de um ano específico.

NÃO é uma previsão de curto prazo. O Windy mostra o vento das próximas horas,
vindo de um modelo global (GFS/ECMWF) rodado quatro vezes por dia; nada disso
cabe num projeto que roda offline, e essas fontes não estão acessíveis daqui.
O que esta base responde é a pergunta que o resto do projeto faz: o risco é
estimado para um MÊS, e o vento que interessa a esse risco é o que aquele mês
costuma trazer.

Por que a média é vetorial
--------------------------
Direção é ângulo, e ângulo não se soma. A média aritmética de 350° e 10° dá
180° — o rumo oposto ao de duas medições que praticamente coincidem. Cada hora
vira um vetor (componentes leste e norte), as componentes são somadas, e a
direção sai de volta do vetor resultante. A decomposição está em
`src/inmet.py`, na `agregar_mensal`, junto com a leitura.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import inmet  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PASTA_BRUTO = RAIZ / "dados" / "bruto" / "inmet"
SAIDA = RAIZ / "dados" / "vento_estacoes.csv"

URL_ANO = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"

# Cinco anos já dão uma climatologia estável: o vento predominante de um mês
# muda pouco de década para década, e cada ano a mais custa ~90 MB de download
# e alguns minutos de leitura. Quem quiser mais passa --de 2016.
PRIMEIRO_ANO = 2021
ULTIMO_ANO = 2025

# Abaixo disso o mês da estação foi medido por tão poucas horas que a direção
# predominante vira ruído. 240 horas são dez dias de medição contínua.
MINIMO_HORAS_NO_MES = 240


def baixar_ano(ano: int, destino: Path) -> bool:
    """Baixa o ZIP de um ano, se ele ainda não estiver aqui."""
    if destino.exists() and destino.stat().st_size > 1_000_000:
        print(f"  {ano}: já baixado")
        return True

    url = URL_ANO.format(ano=ano)
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(pedido, timeout=600) as resposta:
            # Grava em pedaços: o ano inteiro não cabe confortavelmente na
            # memória junto com o resto do processamento.
            parcial = destino.with_suffix(".parcial")
            total = 0
            with open(parcial, "wb") as arquivo:
                while True:
                    pedaco = resposta.read(1 << 20)
                    if not pedaco:
                        break
                    arquivo.write(pedaco)
                    total += len(pedaco)
            # Só vira o arquivo final quando terminou de baixar: um download
            # interrompido não pode parecer um ZIP completo na próxima vez.
            parcial.replace(destino)
        print(f"  {ano}: {total / 1e6:.0f} MB")
        return True
    except Exception as erro:  # noqa: BLE001 - qualquer falha de rede serve
        print(f"  {ano}: não baixou ({type(erro).__name__}: {erro})")
        return False


def direcao_do_vetor(u, v):
    """
    De volta do vetor para a direção meteorológica, em graus.

    Desfaz o que `agregar_mensal` fez: o vetor aponta para onde o vento vai, e
    a direção publicada diz de onde ele vem. O `% 360` devolve o resultado à
    volta de sempre, porque `arctan2` responde de -180 a 180.
    """
    graus = np.degrees(np.arctan2(-u, -v))
    return (graus + 360) % 360


def montar(mensal: pd.DataFrame) -> pd.DataFrame:
    """Reduz o mensal por ano a uma linha por estação e mês."""
    com_vento = mensal[mensal["vento_horas"] >= MINIMO_HORAS_NO_MES].copy()
    if com_vento.empty:
        raise SystemExit(
            "Nenhum mês com horas de vento suficientes. "
            "Os arquivos baixados têm coluna de vento?"
        )

    # Somar as componentes através dos anos é o que transforma "o vento de
    # março de 2019" em "o vento de um março qualquer". O peso pelas horas
    # medidas impede que um ano de estação quase fora do ar pese igual a um
    # ano inteiro de medição.
    com_vento["peso"] = com_vento["vento_horas"]
    for componente in ("vento_u_ms", "vento_v_ms", "vento_velocidade_ms"):
        com_vento[componente] = com_vento[componente] * com_vento["peso"]

    agrupado = com_vento.groupby(
        ["codigo_estacao", "estacao", "uf", "mes"], as_index=False
    ).agg(
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        u=("vento_u_ms", "sum"),
        v=("vento_v_ms", "sum"),
        velocidade=("vento_velocidade_ms", "sum"),
        peso=("peso", "sum"),
        anos=("ano", "nunique"),
    )

    for componente in ("u", "v", "velocidade"):
        agrupado[componente] = agrupado[componente] / agrupado["peso"]

    agrupado["direcao_graus"] = direcao_do_vetor(agrupado["u"], agrupado["v"])

    # O módulo do vetor médio dividido pela velocidade média é a CONSTÂNCIA do
    # vento: 1 quer dizer que ele soprou sempre para o mesmo lado (alísios),
    # perto de 0 que a direção variou tanto que a predominante quase não diz
    # nada. Sem esse número, uma seta firme e uma seta que é pura média de
    # caos ficariam idênticas no mapa.
    modulo = np.hypot(agrupado["u"], agrupado["v"])
    agrupado["constancia"] = (
        modulo / agrupado["velocidade"].clip(lower=0.01)
    ).clip(0, 1)

    agrupado = agrupado.rename(columns={"velocidade": "velocidade_ms"})
    agrupado["horas_medidas"] = agrupado["peso"].astype(int)

    colunas = ["codigo_estacao", "estacao", "uf", "mes", "latitude", "longitude",
               "u", "v", "velocidade_ms", "direcao_graus", "constancia",
               "anos", "horas_medidas"]
    saida = agrupado[colunas].sort_values(["codigo_estacao", "mes"])

    for coluna in ("u", "v", "velocidade_ms", "direcao_graus", "constancia"):
        saida[coluna] = saida[coluna].round(3)

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
                "de endereço — veja URL_ANO no topo deste arquivo."
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
          f"{estacoes} estações, {saida['mes'].nunique()} meses")
    print(f"velocidade média {saida['velocidade_ms'].mean():.1f} m/s, "
          f"constância média {saida['constancia'].mean():.2f}")


if __name__ == "__main__":
    main()
