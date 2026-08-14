"""
Leitura dos dados meteorológicos do INMET.

O que este módulo resolve
-------------------------
O Atlas de Desastres diz *o que aconteceu*, mas não traz o gatilho: a chuva.
Este módulo lê os arquivos das estações automáticas do INMET, agrega os dados
horários em valores mensais por estação e monta as variáveis climáticas que o
modelo pode usar.

Formato dos arquivos
--------------------
Cada estação vira um CSV dentro do ZIP anual, com esta estrutura:

    REGIAO:;SE
    UF:;RJ
    ESTACAO:;PETROPOLIS
    CODIGO (WMO):;A610
    LATITUDE:;-22,50472
    LONGITUDE:;-43,17805
    ALTITUDE:;800,00
    DATA DE FUNDACAO:;01/01/07
    Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);...

    codificação latin-1 · separador ';' · decimal ',' · faltante -9999

**Os nomes das colunas mudam entre os anos.** O INMET alterou grafias,
acentuação e o formato da data ao longo do tempo. Por isso as colunas aqui não
são procuradas pelo nome exato, e sim por palavra-chave normalizada — é a
única forma de um mesmo código ler 2010 e 2025.

Como obter os dados
-------------------
Baixe os anos que quiser em https://portal.inmet.gov.br/dadoshistoricos
(um ZIP por ano) e descompacte tudo em `dados/bruto/inmet/`. Não importa se os
CSVs ficam soltos ou em subpastas por ano: a busca é recursiva.
"""

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
PASTA_INMET = RAIZ / "dados" / "bruto" / "inmet"

URL_INMET = "https://portal.inmet.gov.br/dadoshistoricos"

LINHAS_METADADOS = 8
SEPARADOR = ";"
DECIMAL = ","
# A ordem importa e não é arbitrária: latin-1 decodifica QUALQUER sequência de
# bytes sem levantar erro, então tentá-la primeiro transformaria um arquivo
# UTF-8 em texto corrompido, silenciosamente. UTF-8 é estrito e falha em bytes
# latin-1, então serve de teste; latin-1 fica por último, como rede de
# segurança que sempre funciona.
CODIFICACOES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
FALTANTE = -9999.0

# Período usado como "normal climatológica": a referência contra a qual a chuva
# de cada mês é comparada. Fica INTEIRAMENTE antes do período de estudo
# (2010–2025), então nenhuma informação do futuro entra no cálculo.
NORMAL_ANO_INICIAL = 2000
NORMAL_ANO_FINAL = 2009

# Mês com menos horas válidas que isto é descartado: estação com metade dos
# registros faltando produziria uma "chuva mensal" falsamente baixa.
MINIMO_HORAS_VALIDAS = 0.5

# Palavras-chave para achar cada coluna, na ordem de preferência. A busca é
# feita sobre o nome normalizado (sem acento, minúsculo).
PADROES_COLUNA = {
    "data": [r"^data"],
    "hora": [r"^hora"],
    "precipitacao": [r"precipitacao total"],
    "temperatura": [
        r"temperatura do ar.*bulbo seco",
        r"^temperatura do ar",
        r"temperatura.*instantanea",
    ],
    "umidade": [
        r"umidade relativa do ar.*horaria",
        r"^umidade relativa",
        r"umidade.*instantanea",
    ],
    "rajada": [r"vento.*rajada"],
}


class ErroInmet(Exception):
    """Problema ao ler ou interpretar os arquivos do INMET."""


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().replace(";", " ").split())


def _ler_texto(caminho: Path) -> str:
    """Lê o arquivo tentando as codificações que o INMET já usou."""
    for codificacao in CODIFICACOES:
        try:
            return caminho.read_text(encoding=codificacao)
        except UnicodeDecodeError:
            continue
    raise ErroInmet(
        f"Não consegui decodificar {caminho.name}. "
        f"Tentei: {', '.join(CODIFICACOES)}."
    )


# Ordem fixa das 8 linhas de cabeçalho, estável em todos os anos publicados.
# Serve de rede quando o rótulo vem ilegível — nos arquivos de 2019 o próprio
# INMET gravou "ESTAC?O" e "REGI?O", com a acentuação corrompida na origem.
ORDEM_METADADOS = ("regiao", "uf", "estacao", "codigo",
                   "latitude", "longitude", "altitude", "fundacao")

# Prefixos curtos de propósito: "esta" casa tanto "estacao" quanto "estac?o".
PREFIXOS_METADADOS = {
    "regi": "regiao",
    "uf": "uf",
    "esta": "estacao",
    "lat": "latitude",
    "long": "longitude",
    "alt": "altitude",
}

NUMERICOS_METADADOS = ("latitude", "longitude", "altitude")


def ler_metadados(texto: str) -> dict:
    """
    Extrai as 8 linhas de cabeçalho (região, UF, nome, código, coordenadas).

    A identificação é feita pelo rótulo, com prefixos curtos para tolerar a
    acentuação corrompida que aparece em alguns anos. Se ainda assim um campo
    obrigatório não for achado, usa-se a posição da linha, que nunca mudou.
    """
    linhas = texto.splitlines()[:LINHAS_METADADOS]
    metadados = {}
    por_posicao = {}

    for indice, linha in enumerate(linhas):
        if SEPARADOR not in linha:
            continue
        rotulo, _, valor = linha.partition(SEPARADOR)
        rotulo = _normalizar(rotulo).rstrip(": ")
        valor = valor.strip().strip(SEPARADOR).strip()

        if indice < len(ORDEM_METADADOS):
            por_posicao[ORDEM_METADADOS[indice]] = valor

        campo = None
        if "codigo" in rotulo:
            campo = "codigo"
        else:
            for prefixo, nome in PREFIXOS_METADADOS.items():
                if rotulo.startswith(prefixo):
                    campo = nome
                    break

        if campo and campo not in metadados:
            metadados[campo] = valor

    # Completa pela posição o que o rótulo não entregou.
    for campo in ("regiao", "uf", "estacao", "codigo", *NUMERICOS_METADADOS):
        if campo not in metadados and campo in por_posicao:
            metadados[campo] = por_posicao[campo]

    for campo in NUMERICOS_METADADOS:
        if campo in metadados:
            metadados[campo] = _para_numero(metadados[campo])

    if metadados.get("uf"):
        metadados["uf"] = str(metadados["uf"]).upper()

    faltando = [c for c in ("uf", "estacao") if not metadados.get(c)]
    if faltando:
        raise ErroInmet(
            f"Cabeçalho sem {', '.join(faltando)}. "
            "O arquivo não parece ser de uma estação do INMET."
        )

    return metadados


def _para_numero(valor: str) -> float | None:
    try:
        return float(str(valor).replace(DECIMAL, "."))
    except (TypeError, ValueError):
        return None


def _achar_colunas(colunas: list[str]) -> dict:
    """Descobre qual coluna do arquivo corresponde a cada grandeza."""
    normalizadas = {coluna: _normalizar(coluna) for coluna in colunas}
    encontradas = {}

    for grandeza, padroes in PADROES_COLUNA.items():
        for padrao in padroes:
            achou = next(
                (original for original, normal in normalizadas.items()
                 if re.search(padrao, normal)),
                None,
            )
            if achou is not None:
                encontradas[grandeza] = achou
                break

    for obrigatoria in ("data", "precipitacao"):
        if obrigatoria not in encontradas:
            raise ErroInmet(
                f"Não achei a coluna de {obrigatoria} no arquivo.\n"
                f"Colunas presentes: {', '.join(colunas[:8])}..."
            )

    return encontradas


def ler_estacao(caminho: Path) -> tuple[dict, pd.DataFrame]:
    """Lê um CSV de estação e devolve (metadados, medições horárias)."""
    caminho = Path(caminho)
    return interpretar_estacao(_ler_texto(caminho))


def _decodificar(bytes_do_arquivo: bytes) -> str:
    """Mesma lógica de _ler_texto, para conteúdo que já está na memória."""
    for codificacao in CODIFICACOES:
        try:
            return bytes_do_arquivo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise ErroInmet(f"Não consegui decodificar o conteúdo. "
                    f"Tentei: {', '.join(CODIFICACOES)}.")


def interpretar_estacao(texto: str) -> tuple[dict, pd.DataFrame]:
    """
    Interpreta o conteúdo de um CSV de estação já lido para a memória.

    Separado de `ler_estacao` para que os arquivos possam vir de dentro de um
    ZIP sem passar pelo disco.
    """
    metadados = ler_metadados(texto)

    from io import StringIO

    linhas = texto.splitlines()
    corpo = "\n".join(linhas[LINHAS_METADADOS:])
    if not corpo.strip():
        raise ErroInmet("Arquivo sem linhas de dados após o cabeçalho.")

    # Ler só as colunas necessárias: cada arquivo do INMET tem 19 colunas e
    # ~8.700 linhas, e são milhares de arquivos. Descartar 13 colunas na
    # leitura corta boa parte do tempo de processamento.
    cabecalho = [c.strip() for c in linhas[LINHAS_METADADOS].split(SEPARADOR)]
    colunas = _achar_colunas([c for c in cabecalho if c])

    dados = pd.read_csv(
        StringIO(corpo), sep=SEPARADOR, decimal=DECIMAL,
        usecols=list(colunas.values()),
        na_values=[str(FALTANTE), FALTANTE, "", " "], low_memory=False,
    )

    renomeadas = pd.DataFrame({
        grandeza: dados[coluna] for grandeza, coluna in colunas.items()
    })

    renomeadas["data"] = _interpretar_data(renomeadas["data"])
    renomeadas = renomeadas[renomeadas["data"].notna()]

    for grandeza in ("precipitacao", "temperatura", "umidade", "rajada"):
        if grandeza in renomeadas.columns:
            valores = pd.to_numeric(renomeadas[grandeza], errors="coerce")
            # -9999 é o código de falta; qualquer coisa próxima disso também.
            renomeadas[grandeza] = valores.where(valores > FALTANTE + 1)
        else:
            renomeadas[grandeza] = np.nan

    # Chuva negativa é erro de registro; zero é o mínimo físico.
    renomeadas["precipitacao"] = renomeadas["precipitacao"].clip(lower=0)

    return metadados, renomeadas


def _interpretar_data(coluna: pd.Series) -> pd.Series:
    """
    Converte a coluna de data, que já apareceu em vários formatos.

    O INMET usou `YYYY-MM-DD`, `YYYY/MM/DD` e `DD/MM/YYYY` ao longo dos anos.
    """
    texto = coluna.astype(str).str.strip().str.replace("/", "-", regex=False)

    convertida = pd.to_datetime(texto, format="%Y-%m-%d", errors="coerce")
    if convertida.isna().mean() > 0.5:
        convertida = pd.to_datetime(texto, format="%d-%m-%Y", errors="coerce")
    if convertida.isna().mean() > 0.5:
        convertida = pd.to_datetime(texto, errors="coerce", dayfirst=True)

    return convertida


def agregar_mensal(medicoes: pd.DataFrame, metadados: dict) -> pd.DataFrame:
    """
    Transforma medições horárias em uma linha por mês.

    Além dos totais e médias, guarda a fração de horas com registro válido:
    é ela que permite descartar meses em que a estação ficou fora do ar.
    """
    dados = medicoes.copy()
    dados["ano"] = dados["data"].dt.year
    dados["mes"] = dados["data"].dt.month

    # A chuva máxima em um dia é o melhor sinal de evento extremo disponível
    # aqui: 300 mm espalhados pelo mês é uma coisa, 300 mm num dia é outra.
    por_dia = dados.groupby(["ano", "mes", dados["data"].dt.day])["precipitacao"].sum()
    por_dia = por_dia.reset_index(name="chuva_dia")

    diario = por_dia.groupby(["ano", "mes"]).agg(
        chuva_max_dia_mm=("chuva_dia", "max"),
        dias_com_chuva=("chuva_dia", lambda s: int((s >= 1.0).sum())),
    )

    mensal = dados.groupby(["ano", "mes"]).agg(
        chuva_total_mm=("precipitacao", "sum"),
        temperatura_media_c=("temperatura", "mean"),
        umidade_media_pct=("umidade", "mean"),
        rajada_max_ms=("rajada", "max"),
        horas_registradas=("precipitacao", "size"),
        horas_validas=("precipitacao", "count"),
    ).join(diario)

    mensal = mensal.reset_index()
    mensal["fracao_valida"] = (
        mensal["horas_validas"] / mensal["horas_registradas"].clip(lower=1)
    )
    # O INMET registra rajada em m/s; km/h é mais legível e é a unidade usada
    # no restante do projeto.
    mensal["rajada_max_kmh"] = mensal["rajada_max_ms"] * 3.6

    mensal["estacao"] = metadados.get("estacao")
    mensal["uf"] = metadados.get("uf")
    mensal["codigo_estacao"] = metadados.get("codigo")

    return mensal.drop(columns=["rajada_max_ms"])


def carregar_pasta(pasta: Path = PASTA_INMET, minimo_valido: float = MINIMO_HORAS_VALIDAS,
                   ao_ler=None) -> pd.DataFrame:
    """
    Lê todos os CSVs de estação de uma pasta (recursivamente) e agrega por mês.

    Arquivos ilegíveis não interrompem o processo: são contados e reportados,
    porque um ZIP do INMET costuma ter alguma estação com arquivo corrompido.
    """
    import zipfile

    pasta = Path(pasta)
    soltos = sorted({*pasta.rglob("*.CSV"), *pasta.rglob("*.csv")})
    zips = sorted({*pasta.rglob("*.ZIP"), *pasta.rglob("*.zip")})

    if not soltos and not zips:
        raise ErroInmet(
            f"Nenhum CSV nem ZIP encontrado em {pasta}.\n\n"
            f"Baixe os anos desejados em {URL_INMET}\n"
            f"e coloque os arquivos em {pasta}.\n"
            "Os ZIPs podem ficar como estão: não é preciso descompactar."
        )

    partes, falhas = [], []

    def processar(texto: str, nome: str) -> None:
        try:
            metadados, medicoes = interpretar_estacao(texto)
            if not medicoes.empty:
                partes.append(agregar_mensal(medicoes, metadados))
        except (ErroInmet, ValueError, KeyError, IndexError) as erro:
            falhas.append((nome, str(erro)[:90]))

        if ao_ler:
            ao_ler(nome, len(partes), len(falhas))

    for arquivo in soltos:
        try:
            processar(_ler_texto(arquivo), arquivo.name)
        except ErroInmet as erro:
            falhas.append((arquivo.name, str(erro)[:90]))

    # Os ZIPs anuais do INMET têm ~565 estações cada e passariam de 10 GB se
    # fossem descompactados. Lê-los direto evita ocupar o disco (e evita que
    # o OneDrive tente sincronizar tudo isso, quando o projeto mora nele).
    for caminho_zip in zips:
        try:
            with zipfile.ZipFile(caminho_zip) as pacote:
                membros = [
                    m for m in pacote.namelist() if m.lower().endswith(".csv")
                ]
                for membro in membros:
                    try:
                        conteudo = pacote.read(membro)
                    except (zipfile.BadZipFile, OSError) as erro:
                        falhas.append((membro, str(erro)[:90]))
                        continue
                    try:
                        processar(_decodificar(conteudo), Path(membro).name)
                    except ErroInmet as erro:
                        falhas.append((Path(membro).name, str(erro)[:90]))
        except (zipfile.BadZipFile, OSError) as erro:
            falhas.append((caminho_zip.name, f"ZIP ilegível: {str(erro)[:70]}"))

    if not partes:
        total = len(soltos) + len(zips)
        raise ErroInmet(
            f"Nenhum dos {total} arquivo(s) pôde ser lido. "
            "Confira se são mesmo dados de estação do INMET."
        )

    mensal = pd.concat(partes, ignore_index=True)

    # Descarta meses com registro incompleto demais para serem confiáveis.
    antes = len(mensal)
    mensal = mensal[mensal["fracao_valida"] >= minimo_valido]

    mensal.attrs["arquivos_lidos"] = len(partes)
    mensal.attrs["arquivos_com_falha"] = falhas
    mensal.attrs["meses_descartados"] = antes - len(mensal)
    return mensal.reset_index(drop=True)


# Colunas climáticas que cada município recebe, e como combiná-las quando a
# fonte é um conjunto de estações (uma região inteira, por exemplo).
AGREGACAO_CLIMA = {
    "chuva_total_mm": "mean",
    "chuva_max_dia_mm": "max",
    "dias_com_chuva": "mean",
    "temperatura_media_c": "mean",
    "umidade_media_pct": "mean",
    "rajada_max_kmh": "max",
}

# Do mais próximo ao mais distante. O nível usado fica registrado em cada
# linha, para a análise poder separar "medido aqui" de "estimado pela UF".
NIVEIS_FONTE = ("municipio", "regiao_imediata", "regiao_intermediaria", "uf")


def atribuir_a_municipios(mensal: pd.DataFrame, casadas: pd.DataFrame,
                          municipios: pd.DataFrame) -> pd.DataFrame:
    """
    Espalha as medições das estações para todos os municípios.

    Só ~600 municípios têm estação; os outros recebem a medição da região a
    que pertencem, buscando do nível mais próximo para o mais distante:
    município → região imediata → região intermediária → UF.

    A coluna `fonte_clima` guarda qual nível foi usado. Isso não é detalhe:
    chuva medida no próprio município e chuva estimada pela média do estado
    têm qualidade muito diferente, e o modelo (e a apresentação) precisam
    poder distinguir.
    """
    estacoes = mensal.merge(
        casadas[["estacao", "uf", "codigo_ibge", "regiao_imediata",
                 "regiao_intermediaria"]],
        on=["estacao", "uf"], how="left",
    )

    resultados = []
    pendentes = municipios.copy()

    for nivel in NIVEIS_FONTE:
        if pendentes.empty:
            break

        chave = "codigo_ibge" if nivel == "municipio" else nivel
        disponivel = estacoes[estacoes[chave].notna()]
        if disponivel.empty:
            continue

        medias = disponivel.groupby([chave, "ano", "mes"]).agg(
            **{coluna: (coluna, como) for coluna, como in AGREGACAO_CLIMA.items()},
            estacoes_usadas=("estacao", "nunique"),
        ).reset_index()

        # No primeiro nível a chave É o codigo_ibge; pedir as duas colunas
        # criaria um rótulo duplicado e o merge falharia.
        colunas = ["codigo_ibge"] if chave == "codigo_ibge" else ["codigo_ibge", chave]
        junto = pendentes[colunas].merge(
            medias, on=chave, how="inner", suffixes=("", "_fonte")
        )
        if junto.empty:
            continue

        junto["fonte_clima"] = nivel
        resultados.append(junto.drop(columns=[c for c in (chave,) if c != "codigo_ibge"]))

        # Município já atendido não desce para o próximo nível.
        atendidos = set(junto["codigo_ibge"])
        pendentes = pendentes[~pendentes["codigo_ibge"].isin(atendidos)]

    if not resultados:
        raise ErroInmet(
            "Nenhum município pôde ser ligado a uma estação. Verifique se a "
            "lista do IBGE e os arquivos do INMET são do mesmo país."
        )

    clima = pd.concat(resultados, ignore_index=True)
    clima.attrs["municipios_sem_clima"] = len(pendentes)
    return clima


def calcular_normais(mensal: pd.DataFrame,
                     ano_inicial: int = NORMAL_ANO_INICIAL,
                     ano_final: int = NORMAL_ANO_FINAL) -> pd.DataFrame:
    """
    Calcula a normal climatológica: a chuva típica de cada estação em cada mês.

    Serve para medir **anomalia** — "choveu 80% acima do normal para um mês de
    março aqui" diz muito mais do que "choveu 210 mm", porque 210 mm é seca no
    litoral amazônico e dilúvio no sertão.

    O período de referência fica inteiramente antes do período de estudo, então
    a normal nunca carrega informação dos anos que o modelo vai prever.
    """
    referencia = mensal[
        (mensal["ano"] >= ano_inicial) & (mensal["ano"] <= ano_final)
    ]

    if referencia.empty:
        return pd.DataFrame(columns=["estacao", "uf", "mes", "chuva_normal_mm",
                                     "anos_na_normal"])

    normais = referencia.groupby(["estacao", "uf", "mes"]).agg(
        chuva_normal_mm=("chuva_total_mm", "mean"),
        anos_na_normal=("ano", "nunique"),
    ).reset_index()

    return normais
