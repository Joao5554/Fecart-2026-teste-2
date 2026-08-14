"""
Ligação entre municípios e regiões do IBGE.

Para que serve
--------------
O INMET tem cerca de 600 estações automáticas; o Brasil tem 5.571 municípios.
A maioria dos municípios **não** tem estação própria, então a chuva precisa vir
da estação mais próxima em termos administrativos.

Este módulo carrega a lista oficial do IBGE e devolve, para cada município, a
qual **região imediata**, **região intermediária** e **UF** ele pertence. Com
isso o ETL do clima pode buscar a medição em três níveis, do mais próximo ao
mais distante:

    estação no próprio município
      -> qualquer estação da região imediata      (~510 regiões)
        -> qualquer estação da região intermediária (~130 regiões)
          -> média da UF

Por que região imediata, e não microrregião
-------------------------------------------
As microrregiões são a divisão antiga do IBGE e deixaram de ser atualizadas —
há município novo sem microrregião definida. As regiões imediatas são a
divisão vigente e cobrem os 5.571 municípios sem buraco.

Como obter o arquivo
--------------------
    curl -o dados/bruto/municipios_ibge.json \\
      https://servicodados.ibge.gov.br/api/v1/localidades/municipios

São 2,4 MB e o download leva segundos. O arquivo não vai para o Git.
"""

import json
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_MUNICIPIOS = RAIZ / "dados" / "bruto" / "municipios_ibge.json"

URL_IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"


class ErroRegioes(Exception):
    """Problema ao ler ou interpretar a lista de municípios do IBGE."""


def normalizar(texto: str) -> str:
    """
    Padroniza um nome para comparação: sem acento, minúsculo, sem pontuação.

    É o que permite casar "PETROPOLIS" (como o INMET escreve) com "Petrópolis"
    (como o IBGE escreve). Sem isso, quase nenhuma estação encontraria seu
    município.
    """
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    limpo = "".join(c if c.isalnum() or c.isspace() else " " for c in sem_acento)
    return " ".join(limpo.lower().split())


def carregar_municipios(caminho: Path = ARQUIVO_MUNICIPIOS) -> pd.DataFrame:
    """
    Lê a lista do IBGE e devolve uma tabela com as regiões de cada município.

    Colunas: codigo_ibge, municipio, nome_busca, uf, regiao_imediata,
    regiao_intermediaria.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroRegioes(
            f"Lista de municípios não encontrada em {caminho}.\n\n"
            "Baixe uma vez com:\n"
            f"  curl -o {caminho.as_posix()} \\\n    {URL_IBGE}"
        )

    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ErroRegioes(f"O arquivo do IBGE não é um JSON válido: {erro}") from erro

    linhas = []
    for municipio in bruto:
        imediata = municipio.get("regiao-imediata") or {}
        intermediaria = imediata.get("regiao-intermediaria") or {}
        uf = intermediaria.get("UF") or {}

        # Municípios antigos podem não ter região imediata; nesses casos a
        # hierarquia antiga (microrregião) ainda serve para achar a UF.
        if not uf:
            micro = municipio.get("microrregiao") or {}
            uf = (micro.get("mesorregiao") or {}).get("UF") or {}

        linhas.append({
            "codigo_ibge": int(municipio["id"]),
            "municipio": municipio["nome"],
            "nome_busca": normalizar(municipio["nome"]),
            "uf": uf.get("sigla"),
            "regiao_imediata": imediata.get("id"),
            "regiao_intermediaria": intermediaria.get("id"),
        })

    tabela = pd.DataFrame(linhas)
    if tabela["uf"].isna().any():
        faltando = int(tabela["uf"].isna().sum())
        raise ErroRegioes(
            f"{faltando} município(s) sem UF na lista do IBGE. "
            "O arquivo pode estar incompleto — baixe de novo."
        )

    return tabela


def casar_estacoes(estacoes: pd.DataFrame, municipios: pd.DataFrame) -> pd.DataFrame:
    """
    Descobre a qual município pertence cada estação do INMET.

    O casamento é por **nome normalizado + UF**. A UF entra na chave porque há
    dezenas de nomes repetidos no Brasil (existem várias "Bom Jesus" e
    "Santa Maria" em estados diferentes); casar só pelo nome jogaria a chuva
    de um estado em outro.

    `estacoes` precisa ter as colunas `estacao` (nome) e `uf`. O resultado
    ganha codigo_ibge, regiao_imediata e regiao_intermediaria — vazios quando
    a estação não encontrou município correspondente.
    """
    estacoes = estacoes.copy()
    estacoes["nome_busca"] = estacoes["estacao"].map(normalizar)
    estacoes["uf"] = estacoes["uf"].str.strip().str.upper()

    referencia = municipios[
        ["nome_busca", "uf", "codigo_ibge", "regiao_imediata", "regiao_intermediaria"]
    ]

    casadas = estacoes.merge(referencia, on=["nome_busca", "uf"], how="left")

    # Nomes de estação às vezes trazem um complemento ("VITORIA DE SANTO ANTAO"
    # vira "VITORIA DE SANTO ANTAO - PE"). Para as que sobraram, tenta casar
    # pelo prefixo mais longo que corresponda a um município daquela UF.
    faltando = casadas["codigo_ibge"].isna()
    if faltando.any():
        casadas = _casar_por_prefixo(casadas, referencia, faltando)

    return casadas


def _casar_por_prefixo(casadas: pd.DataFrame, referencia: pd.DataFrame,
                       faltando: pd.Series) -> pd.DataFrame:
    """Segunda tentativa: nome da estação começando com o nome do município."""
    por_uf = {
        uf: bloco.sort_values("nome_busca", key=lambda s: s.str.len(),
                              ascending=False)
        for uf, bloco in referencia.groupby("uf")
    }

    for indice in casadas.index[faltando]:
        nome = casadas.at[indice, "nome_busca"]
        candidatos = por_uf.get(casadas.at[indice, "uf"])
        if candidatos is None:
            continue

        for _, municipio in candidatos.iterrows():
            if nome.startswith(municipio["nome_busca"] + " "):
                for coluna in ("codigo_ibge", "regiao_imediata",
                               "regiao_intermediaria"):
                    casadas.at[indice, coluna] = municipio[coluna]
                break

    return casadas


def resumir_cobertura(casadas: pd.DataFrame, municipios: pd.DataFrame) -> dict:
    """
    Mede quanto do país fica coberto por cada nível de busca.

    Serve para decidir se vale usar os dados de clima: se só metade dos
    municípios alcança uma estação, o ganho será limitado e é melhor saber
    disso antes de treinar.
    """
    com_estacao = casadas[casadas["codigo_ibge"].notna()]

    municipios_com = set(com_estacao["codigo_ibge"])
    imediatas_com = set(com_estacao["regiao_imediata"].dropna())
    intermediarias_com = set(com_estacao["regiao_intermediaria"].dropna())
    ufs_com = set(com_estacao["uf"])

    total = len(municipios)
    return {
        "estacoes": int(len(casadas)),
        "estacoes_sem_municipio": int(casadas["codigo_ibge"].isna().sum()),
        "municipios_com_estacao_propria": int(
            municipios["codigo_ibge"].isin(municipios_com).sum()
        ),
        "municipios_via_regiao_imediata": int(
            municipios["regiao_imediata"].isin(imediatas_com).sum()
        ),
        "municipios_via_regiao_intermediaria": int(
            municipios["regiao_intermediaria"].isin(intermediarias_com).sum()
        ),
        "municipios_via_uf": int(municipios["uf"].isin(ufs_com).sum()),
        "total_municipios": total,
    }
