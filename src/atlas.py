"""
Conversão do Atlas de Desastres (S2iD/SEDEC) no dataset de treino.

O arquivo bruto do Atlas é um registro de OCORRÊNCIAS: cada linha é um
desastre que aconteceu. Para treinar um classificador de risco faltam duas
coisas, e é isso que este módulo constrói:

1. **Exemplos negativos.** Um modelo que só vê desastres aprende que tudo é
   desastre. Precisamos também de (município, mês, tipo) em que NADA
   aconteceu — são eles que definem o nível "baixo".

2. **Features sem vazamento temporal.** Todas as variáveis de um mês-alvo são
   calculadas usando exclusivamente ocorrências ANTERIORES a ele. Se o
   histórico incluísse o próprio mês, o modelo "preveria" o passado e a
   acurácia sairia alta e inútil.

O que o Atlas fornece é histórico, sazonalidade e geografia. Dados
climáticos (chuva, temperatura, umidade) NÃO estão neste arquivo — quando
vierem do INMET/CEMADEN, entram como colunas novas aqui.

Formato do arquivo bruto (verificado na versão 1.1, de 2026-08-06):
    separador ';', decimal ',', codificação cp850, datas DD/MM/AAAA.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import esquema  # noqa: E402

# Leitura do arquivo bruto -------------------------------------------------

SEPARADOR = ";"
DECIMAL = ","
CODIFICACAO = "cp850"
FORMATO_DATA = "%d/%m/%Y"

COLUNAS_ATLAS = [
    "Nome_Municipio", "Sigla_UF", "regiao", "Data_Evento",
    "descricao_tipologia", "Cod_IBGE_Mun", "Status",
    "DH_MORTOS", "DH_total_danos_humanos_diretos", "PE_PLePR",
]

# As tipologias do Atlas agrupadas nas classes que o modelo usa.
# Tipologias fora deste mapa são descartadas (ver TIPOLOGIAS_DESCARTADAS).
TIPOLOGIA_PARA_GRUPO = {
    "Estiagem e Seca": "ESTIAGEM_SECA",
    "Enxurradas": "ENXURRADA",
    "Chuvas Intensas": "CHUVAS_INTENSAS",
    "Inundações": "INUNDACAO",
    "Vendavais e Ciclones": "VENDAVAL_CICLONE",
    "Tornado": "VENDAVAL_CICLONE",
    "Incêndio Florestal": "INCENDIO_FLORESTAL",
    "Granizo": "GRANIZO",
    "Alagamentos": "ALAGAMENTO",
    "Movimento de Massa": "DESLIZAMENTO",
    "Erosão": "EROSAO",
}

# Descartadas de propósito: "Outros" não tem definição própria; doenças
# infecciosas não são desastre geofísico/climático; ondas de frio/calor e
# rompimento de barragens somam menos de 1% e não têm variável explicativa
# no que o Atlas oferece hoje.
TIPOLOGIAS_DESCARTADAS = (
    "Outros", "Doenças infecciosas", "Onda de Frio",
    "Onda de Calor e Baixa Umidade", "Rompimento/Colapso de barragens",
)

STATUS_RECONHECIDO = "Reconhecido"


class ErroAtlas(Exception):
    """Problema ao ler ou interpretar o arquivo bruto do Atlas."""


def _indice_mes(ano, mes):
    """Converte (ano, mês) num número inteiro contínuo, para comparar datas."""
    return (np.asarray(ano) - 1900) * 12 + (np.asarray(mes) - 1)


def carregar_atlas(caminho: Path) -> pd.DataFrame:
    """Lê o CSV bruto do Atlas e devolve as ocorrências limpas."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroAtlas(
            f"Arquivo do Atlas não encontrado: {caminho}\n"
            "Baixe a base consolidada em https://atlasdigital.mi.gov.br "
            "e salve em dados/bruto/."
        )

    try:
        dados = pd.read_csv(
            caminho, sep=SEPARADOR, encoding=CODIFICACAO, decimal=DECIMAL,
            usecols=COLUNAS_ATLAS, low_memory=False,
        )
    except ValueError as erro:
        raise ErroAtlas(
            f"O arquivo não tem as colunas esperadas do Atlas ({erro}).\n"
            "Confira se é a base consolidada (BD_Atlas_..._Consolidado.csv)."
        ) from erro

    dados = dados.rename(columns={
        "Nome_Municipio": "municipio",
        "Sigla_UF": "uf",
        "Cod_IBGE_Mun": "codigo_ibge",
        "descricao_tipologia": "tipologia",
        "Status": "status",
        "DH_MORTOS": "mortos",
        "DH_total_danos_humanos_diretos": "afetados",
        "PE_PLePR": "prejuizo",
    })

    data = pd.to_datetime(dados["Data_Evento"], format=FORMATO_DATA, errors="coerce")
    dados = dados.assign(ano=data.dt.year, mes=data.dt.month)
    dados = dados[data.notna()]

    dados["grupo_desastre"] = dados["tipologia"].map(TIPOLOGIA_PARA_GRUPO)
    dados = dados[dados["grupo_desastre"].notna()]

    dados["regiao"] = dados["regiao"].str.strip().str.title()
    dados["uf"] = dados["uf"].str.strip().str.upper()

    for coluna in ("mortos", "afetados", "prejuizo"):
        dados[coluna] = pd.to_numeric(dados[coluna], errors="coerce").fillna(0.0)
        # O Atlas tem alguns valores negativos por erro de digitação.
        dados[coluna] = dados[coluna].clip(lower=0)

    dados["reconhecido"] = dados["status"] == STATUS_RECONHECIDO
    dados["codigo_ibge"] = pd.to_numeric(dados["codigo_ibge"], errors="coerce")
    dados = dados[dados["codigo_ibge"].notna()]
    dados["codigo_ibge"] = dados["codigo_ibge"].astype(int)

    colunas = [
        "codigo_ibge", "municipio", "uf", "regiao", "ano", "mes",
        "grupo_desastre", "reconhecido", "mortos", "afetados", "prejuizo",
    ]
    return dados[colunas].reset_index(drop=True)


def agregar_por_mes(ocorrencias: pd.DataFrame) -> pd.DataFrame:
    """
    Junta as ocorrências num registro por (município, tipo, ano, mês).

    O Atlas pode ter vários protocolos para o mesmo evento; o que interessa
    para o rótulo é se houve ocorrência no mês e qual a gravidade máxima.
    """
    agrupado = ocorrencias.groupby(
        ["codigo_ibge", "grupo_desastre", "ano", "mes"], as_index=False
    ).agg(
        municipio=("municipio", "first"),
        uf=("uf", "first"),
        regiao=("regiao", "first"),
        reconhecido=("reconhecido", "max"),
        mortos=("mortos", "sum"),
        afetados=("afetados", "sum"),
        prejuizo=("prejuizo", "sum"),
    )
    agrupado["indice_mes"] = _indice_mes(agrupado["ano"], agrupado["mes"])
    return agrupado


def classificar_risco(reconhecido, mortos) -> str:
    """
    Traduz a gravidade da ocorrência no nível de risco.

    A regra usa o que o próprio S2iD registra:
      - alto  : houve mortos, ou a União reconheceu emergência/calamidade;
      - medio : houve ocorrência registrada, sem reconhecimento nem mortos;
      - baixo : não houve ocorrência (linhas construídas por este módulo).

    Esta escolha é metodológica e deve ser descrita na apresentação: o Atlas
    registra o que aconteceu, não um "nível de risco" pronto.
    """
    if reconhecido or mortos > 0:
        return "alto"
    return "medio"


def _features_de_uma_serie(alvos: np.ndarray, eventos: np.ndarray,
                           pesos: dict[str, np.ndarray] | None = None) -> dict:
    """
    Calcula, para cada mês-alvo, estatísticas do passado daquela série.

    `alvos` são os meses que queremos descrever; `eventos` são os meses em que
    houve ocorrência, já ordenados. O corte usa busca binária com `side="left"`,
    ou seja, conta apenas o que é ESTRITAMENTE anterior ao mês-alvo — é isso
    que impede o vazamento temporal.
    """
    antes = np.searchsorted(eventos, alvos, side="left")
    antes_12 = np.searchsorted(eventos, alvos - 12, side="left")
    antes_24 = np.searchsorted(eventos, alvos - 24, side="left")
    antes_60 = np.searchsorted(eventos, alvos - 60, side="left")

    resultado = {
        "ocorrencias_total_historico": antes.astype(float),
        "ocorrencias_12m": (antes - antes_12).astype(float),
        "ocorrencias_24m": (antes - antes_24).astype(float),
        "ocorrencias_60m": (antes - antes_60).astype(float),
    }

    # Meses desde a última ocorrência. Sem histórico, usamos -1 junto com a
    # coluna `ja_ocorreu`; um número grande arbitrário confundiria o modelo.
    #
    # O caso de série vazia precisa de desvio próprio: indexar um array vazio
    # falha mesmo dentro de np.where, que avalia os dois lados. E ele acontece
    # de verdade — basta consultar um tipo de desastre que nunca ocorreu
    # naquele município.
    if len(eventos) == 0:
        resultado["meses_desde_ultima_ocorrencia"] = np.full(len(alvos), -1.0)
        resultado["anos_de_historico"] = np.zeros(len(alvos))
    else:
        ultima = eventos[np.clip(antes - 1, 0, None)]
        resultado["meses_desde_ultima_ocorrencia"] = np.where(
            antes > 0, alvos - ultima, -1
        ).astype(float)
        resultado["anos_de_historico"] = np.where(
            antes > 0, (alvos - eventos[0]) / 12.0, 0.0
        )

    resultado["ja_ocorreu"] = (antes > 0).astype(float)

    if pesos:
        for nome, valores in pesos.items():
            acumulado = np.concatenate([[0.0], np.cumsum(valores)])
            resultado[nome] = acumulado[antes]

    return resultado


def _ocorrencias_mesmo_mes(alvos: np.ndarray, eventos: np.ndarray) -> np.ndarray:
    """
    Quantas vezes esse tipo de desastre já ocorreu NESTE mês do calendário.

    Captura a sazonalidade local: seca no sertão tem época, assim como
    deslizamento no litoral. Só conta ocorrências anteriores ao mês-alvo.
    """
    resultado = np.zeros(len(alvos))
    if len(eventos) == 0:
        return resultado

    calendario_evento = eventos % 12
    for mes_calendario in np.unique(alvos % 12):
        selecao = alvos % 12 == mes_calendario
        mesmos = eventos[calendario_evento == mes_calendario]
        if len(mesmos):
            resultado[selecao] = np.searchsorted(
                mesmos, alvos[selecao], side="left"
            )
    return resultado


def calcular_features(historico: pd.DataFrame, alvos: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula as features históricas para um conjunto de meses-alvo.

    `historico` é a saída de `agregar_por_mes` (um registro por município,
    tipo e mês em que houve ocorrência). `alvos` precisa ter as colunas
    codigo_ibge, grupo_desastre e indice_mes.

    Esta é a ÚNICA função que calcula features no projeto. O dataset de treino
    e as consultas da API passam por aqui, então é impossível o modelo ser
    treinado com uma conta e consultado com outra.
    """
    partes = []
    indice_historico = {
        chave: bloco.sort_values("indice_mes")
        for chave, bloco in historico.groupby(["codigo_ibge", "grupo_desastre"])
    }

    for chave, bloco_alvo in alvos.groupby(["codigo_ibge", "grupo_desastre"], sort=False):
        serie = indice_historico.get(chave)
        if serie is None:
            serie = historico.iloc[0:0]

        eventos = serie["indice_mes"].to_numpy()
        meses_alvo = bloco_alvo["indice_mes"].to_numpy()

        calculadas = _features_de_uma_serie(
            meses_alvo, eventos,
            pesos={
                "mortos_historico": serie["mortos"].to_numpy(),
                "afetados_historico": serie["afetados"].to_numpy(),
                "prejuizo_historico": serie["prejuizo"].to_numpy(),
                "reconhecimentos_historico": serie["reconhecido"].to_numpy().astype(float),
            },
        )
        calculadas["ocorrencias_mesmo_mes_historico"] = _ocorrencias_mesmo_mes(
            meses_alvo, eventos
        )

        partes.append(bloco_alvo.reset_index(drop=True).assign(**calculadas))

    dados = pd.concat(partes, ignore_index=True)
    return _adicionar_contexto(dados, historico)


def features_para_consulta(ocorrencias: pd.DataFrame, codigo_ibge: int,
                           grupo_desastre: str, ano: int, mes: int) -> dict:
    """
    Monta as features de UMA consulta, a partir do histórico do município.

    É o que permite a interface perguntar apenas "qual município, qual tipo de
    desastre e qual mês" — as quinze variáveis históricas são calculadas aqui,
    exatamente como no treino, em vez de serem digitadas por quem consulta.
    """
    historico = agregar_por_mes(ocorrencias)
    alvo = pd.DataFrame([{
        "codigo_ibge": int(codigo_ibge),
        "grupo_desastre": grupo_desastre,
        "indice_mes": int(_indice_mes(ano, mes)),
    }])

    linha = calcular_features(historico, alvo).iloc[0]

    features = {
        "mes": mes,
        "prejuizo_historico_log": float(np.log1p(linha["prejuizo_historico"])),
    }
    for coluna in esquema.COLUNAS_NUMERICAS:
        if coluna not in features:
            features[coluna] = float(linha[coluna])
    return features


def construir_dataset(
    ocorrencias: pd.DataFrame,
    ano_inicial: int = 2010,
    ano_final: int = 2025,
    negativos_por_positivo: int = 3,
    semente: int = 42,
) -> pd.DataFrame:
    """
    Monta o dataset de treino a partir das ocorrências do Atlas.

    Para cada par (município, tipo de desastre) com histórico, considera os
    meses do período: aqueles com ocorrência viram exemplos positivos
    (medio/alto) e uma amostra dos demais vira exemplo negativo (baixo).

    `negativos_por_positivo` controla o tamanho do dataset. A proporção real
    de meses sem desastre é muito maior; a amostragem mantém o arquivo
    treinável, e o `class_weight` do modelo corrige o desequilíbrio restante.
    """
    rng = np.random.default_rng(semente)

    mensal = agregar_por_mes(ocorrencias)
    mensal = mensal[(mensal["ano"] >= ano_inicial) & (mensal["ano"] <= ano_final)]
    if mensal.empty:
        raise ErroAtlas(
            f"Nenhuma ocorrência entre {ano_inicial} e {ano_final}. "
            "Verifique o período pedido."
        )

    inicio = _indice_mes(ano_inicial, 1)
    fim = _indice_mes(ano_final, 12)

    # Identidade de cada município (nome/UF/região vêm do registro mais recente).
    municipios = (
        mensal.sort_values("indice_mes")
        .groupby("codigo_ibge")
        .agg(municipio=("municipio", "last"), uf=("uf", "last"), regiao=("regiao", "last"))
    )

    # --- 1. Linhas-alvo: positivos (com ocorrência) e negativos (sem) --------
    linhas_positivas = mensal[["codigo_ibge", "grupo_desastre", "indice_mes"]].copy()
    linhas_positivas["houve_ocorrencia"] = True

    negativas = []
    for (ibge, grupo), bloco in mensal.groupby(["codigo_ibge", "grupo_desastre"]):
        meses_com_evento = np.sort(bloco["indice_mes"].unique())
        # Todo o período entra como candidato a exemplo negativo, INCLUSIVE os
        # meses anteriores à primeira ocorrência conhecida.
        #
        # Restringir aos meses posteriores parece razoável ("antes não há
        # histórico"), mas cria um viés grave: as únicas linhas com histórico
        # zero passariam a ser justamente as primeiras ocorrências, todas
        # positivas. O modelo aprenderia "nunca aconteceu => vai acontecer" e
        # devolveria risco médio para qualquer município sem histórico.
        candidatos = np.arange(inicio, fim + 1)
        candidatos = np.setdiff1d(candidatos, meses_com_evento, assume_unique=False)
        if len(candidatos) == 0:
            continue

        quantidade = min(len(candidatos), negativos_por_positivo * len(meses_com_evento))
        sorteados = rng.choice(candidatos, size=quantidade, replace=False)
        negativas.append(pd.DataFrame({
            "codigo_ibge": ibge,
            "grupo_desastre": grupo,
            "indice_mes": sorteados,
            "houve_ocorrencia": False,
        }))

    alvo = pd.concat([linhas_positivas] + negativas, ignore_index=True)
    alvo = alvo[(alvo["indice_mes"] >= inicio) & (alvo["indice_mes"] <= fim)]

    # --- 2. Features históricas ---------------------------------------------
    # As ocorrências usadas no histórico incluem TODO o período disponível
    # (inclusive antes de ano_inicial): quanto mais passado, melhor — e não há
    # vazamento, porque o corte é sempre "estritamente antes do mês-alvo".
    historico = agregar_por_mes(ocorrencias)
    dados = calcular_features(historico, alvo)

    # --- 4. Rótulo ----------------------------------------------------------
    chaves = ["codigo_ibge", "grupo_desastre", "indice_mes"]
    gravidade = mensal.set_index(chaves)[["reconhecido", "mortos"]]
    dados = dados.join(gravidade, on=chaves)

    dados[esquema.COLUNA_ALVO] = np.where(
        ~dados["houve_ocorrencia"], "baixo",
        np.where(
            dados["reconhecido"].fillna(False) | (dados["mortos"].fillna(0) > 0),
            "alto", "medio",
        ),
    )

    # --- 5. Colunas finais --------------------------------------------------
    dados["ano"] = 1900 + dados["indice_mes"] // 12
    dados["mes"] = dados["indice_mes"] % 12 + 1
    dados = dados.join(municipios, on="codigo_ibge")

    # Prejuízo em reais varia por ordens de grandeza; o log comprime a escala.
    dados["prejuizo_historico_log"] = np.log1p(dados["prejuizo_historico"])
    dados = dados.drop(columns=[
        "indice_mes", "houve_ocorrencia", "reconhecido", "mortos", "prejuizo_historico",
    ])

    colunas = (
        esquema.COLUNAS_IDENTIFICACAO
        + esquema.COLUNAS_CATEGORICAS
        + esquema.COLUNAS_NUMERICAS
        + [esquema.COLUNA_ALVO]
    )
    faltando = [c for c in colunas if c not in dados.columns]
    if faltando:
        raise ErroAtlas(f"Colunas não produzidas pelo ETL: {faltando}")

    dados = dados[colunas].sort_values(["ano", "mes", "codigo_ibge"])
    return dados.reset_index(drop=True)


def _adicionar_contexto(dados: pd.DataFrame, historico: pd.DataFrame) -> pd.DataFrame:
    """
    Acrescenta o que aconteceu em volta: no município (todos os tipos) e na UF.

    Um município que vem sofrendo eventos de vários tipos está em situação
    diferente de um que teve um caso isolado. E um tipo de desastre em alta na
    UF inteira sinaliza condição regional — seca, por exemplo, não respeita
    divisa municipal.
    """
    por_municipio = (
        historico.groupby(["codigo_ibge", "indice_mes"]).size().rename("n").reset_index()
    )
    uf_por_ibge = historico.drop_duplicates("codigo_ibge").set_index("codigo_ibge")["uf"]
    historico = historico.assign(uf_ref=historico["codigo_ibge"].map(uf_por_ibge))
    por_uf = (
        historico.groupby(["uf_ref", "grupo_desastre", "indice_mes"])
        .size().rename("n").reset_index()
    )

    mapa_municipio = {
        ibge: (bloco["indice_mes"].to_numpy(), bloco["n"].to_numpy())
        for ibge, bloco in por_municipio.sort_values("indice_mes").groupby("codigo_ibge")
    }
    mapa_uf = {
        chave: (bloco["indice_mes"].to_numpy(), bloco["n"].to_numpy())
        for chave, bloco in por_uf.sort_values("indice_mes").groupby(
            ["uf_ref", "grupo_desastre"]
        )
    }

    dados = dados.copy()
    dados["ocorrencias_municipio_12m"] = 0.0
    dados["ocorrencias_uf_grupo_12m"] = 0.0
    vazio = (np.array([]), np.array([]))

    for ibge, bloco in dados.groupby("codigo_ibge", sort=False):
        meses, contagens = mapa_municipio.get(ibge, vazio)
        dados.loc[bloco.index, "ocorrencias_municipio_12m"] = _soma_janela(
            bloco["indice_mes"].to_numpy(), meses, contagens
        )

    dados["_uf_ref"] = dados["codigo_ibge"].map(uf_por_ibge)
    for chave, bloco in dados.groupby(["_uf_ref", "grupo_desastre"], sort=False):
        meses, contagens = mapa_uf.get(chave, vazio)
        dados.loc[bloco.index, "ocorrencias_uf_grupo_12m"] = _soma_janela(
            bloco["indice_mes"].to_numpy(), meses, contagens
        )

    return dados.drop(columns=["_uf_ref"])


def _soma_janela(alvos: np.ndarray, meses: np.ndarray,
                 contagens: np.ndarray) -> np.ndarray:
    """Soma as contagens nos 12 meses anteriores a cada alvo (sem incluí-lo)."""
    if len(meses) == 0:
        return np.zeros(len(alvos))
    acumulado = np.concatenate([[0.0], np.cumsum(contagens)])
    fim = np.searchsorted(meses, alvos, side="left")
    inicio = np.searchsorted(meses, alvos - 12, side="left")
    return acumulado[fim] - acumulado[inicio]
