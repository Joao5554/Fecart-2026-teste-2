"""
Contrato de dados do projeto — fonte única da verdade.

Este arquivo define QUAIS colunas o dataset precisa ter, o tipo de cada uma,
a unidade e a faixa de valores aceita. O treinamento e o backend leem daqui,
então nunca há divergência entre o que o modelo aprendeu e o que a API recebe.

Formato dos dados
-----------------
Uma linha = um município, em um mês, para um grupo de desastre.

    codigo_ibge | ano | mes | cobrade_grupo    | ... | nivel_risco
    3550308     | 2024| 2   | INUNDACAO        | ... | alto
    3550308     | 2024| 2   | DESLIZAMENTO     | ... | medio
    3550308     | 2024| 3   | INUNDACAO        | ... | baixo

Ou seja, o mesmo município aparece várias vezes: uma vez por mês e por tipo
de desastre. Isso permite um único modelo cobrir todos os tipos, como no S2iD.

Quando a base real chegar
-------------------------
Renomeie as colunas do CSV para os nomes abaixo (ou ajuste os nomes aqui).
Não é preciso mexer no treinamento nem no backend.
"""

from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Alvo: o que o modelo prevê
# --------------------------------------------------------------------------

COLUNA_ALVO = "nivel_risco"

# A ordem importa: define a ordem das probabilidades devolvidas pela API
# e a ordem das linhas/colunas da matriz de confusão.
CLASSES_RISCO = ["baixo", "medio", "alto"]

# Usado no mapa interativo para colorir os municípios.
CORES_RISCO = {
    "baixo": "#2E7D32",   # verde
    "medio": "#F9A825",   # amarelo
    "alto": "#C62828",    # vermelho
}


# --------------------------------------------------------------------------
# Grupos de desastre (COBRADE — Codificação Brasileira de Desastres)
# --------------------------------------------------------------------------
# Agrupados para o modelo. O código COBRADE completo tem 4 níveis; aqui usamos
# o agrupamento que a Defesa Civil usa nos relatórios públicos.

GRUPOS_COBRADE = {
    "INUNDACAO": "1.2.1.0.0 — Inundações",
    "ENXURRADA": "1.2.2.0.0 — Enxurradas",
    "ALAGAMENTO": "1.2.3.0.0 — Alagamentos",
    "DESLIZAMENTO": "1.1.3.1.4 — Movimento de massa / deslizamentos",
    "ESTIAGEM_SECA": "1.4.1.0.0 — Estiagem e seca",
    "VENDAVAL_CICLONE": "1.3.2.1.5 — Vendaval / ciclone",
    "GRANIZO": "1.3.2.1.3 — Chuvas de granizo",
    "INCENDIO_FLORESTAL": "1.4.1.4.0 — Incêndio florestal",
    "EROSAO": "1.1.4.0.0 — Erosão",
}

REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

BIOMAS = ["Amazonia", "Cerrado", "Mata Atlantica", "Caatinga", "Pampa", "Pantanal"]

UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
]


# --------------------------------------------------------------------------
# Descrição de cada coluna
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Coluna:
    """Descreve uma coluna do dataset."""

    nome: str
    descricao: str
    tipo: str                       # "numerico" ou "categorico"
    unidade: str = ""
    minimo: float | None = None     # faixa válida (usada na validação)
    maximo: float | None = None
    categorias: list[str] = field(default_factory=list)
    permite_nulo: bool = False      # nulos são imputados no pipeline
    fonte: str = ""                 # de onde vem o dado, para facilitar a coleta


# Colunas de identificação: acompanham a linha, mas NÃO entram no modelo.
# Servem para localizar o município no mapa e rastrear a previsão.
IDENTIFICACAO = [
    Coluna("codigo_ibge", "Código IBGE do município (7 dígitos)", "numerico",
           minimo=1_000_000, maximo=9_999_999, fonte="IBGE"),
    Coluna("municipio", "Nome do município", "categorico", fonte="IBGE"),
    Coluna("ano", "Ano de referência do registro", "numerico",
           minimo=1990, maximo=2100, fonte="S2iD"),
    Coluna("mes", "Mês de referência (1 a 12)", "numerico",
           minimo=1, maximo=12, fonte="S2iD"),
]


# Colunas categóricas que entram no modelo.
CATEGORICAS = [
    Coluna("uf", "Unidade federativa", "categorico",
           categorias=UFS, fonte="IBGE"),
    Coluna("regiao", "Região do país", "categorico",
           categorias=REGIOES, fonte="IBGE"),
    Coluna("bioma", "Bioma predominante no município", "categorico",
           categorias=BIOMAS, fonte="IBGE / MapBiomas"),
    Coluna("cobrade_grupo", "Grupo de desastre (COBRADE)", "categorico",
           categorias=list(GRUPOS_COBRADE), fonte="S2iD"),
]


# Colunas numéricas que entram no modelo, separadas por origem do dado.

# --- Características fixas do município (mudam pouco ao longo do tempo) ---
NUMERICAS_TERRITORIO = [
    Coluna("latitude", "Latitude do centroide do município", "numerico", "graus",
           minimo=-34.0, maximo=6.0, fonte="IBGE"),
    Coluna("longitude", "Longitude do centroide do município", "numerico", "graus",
           minimo=-74.0, maximo=-34.0, fonte="IBGE"),
    Coluna("area_km2", "Área territorial", "numerico", "km²",
           minimo=1.0, maximo=200_000.0, fonte="IBGE"),
    Coluna("populacao", "População estimada", "numerico", "habitantes",
           minimo=0.0, maximo=15_000_000.0, fonte="IBGE"),
    Coluna("densidade_demografica", "Densidade demográfica", "numerico", "hab/km²",
           minimo=0.0, maximo=15_000.0, fonte="IBGE"),
    Coluna("altitude_media_m", "Altitude média", "numerico", "m",
           minimo=-10.0, maximo=3_000.0, fonte="IBGE / SRTM"),
    Coluna("declividade_media_graus", "Declividade média do terreno", "numerico", "graus",
           minimo=0.0, maximo=60.0, fonte="SRTM / CPRM"),
    Coluna("percentual_area_urbana", "Percentual de área urbanizada", "numerico", "%",
           minimo=0.0, maximo=100.0, fonte="IBGE"),
    Coluna("percentual_domicilios_area_risco",
           "Percentual de domicílios em área de risco", "numerico", "%",
           minimo=0.0, maximo=100.0, fonte="IBGE — Áreas de Risco"),
    Coluna("indice_vegetacao", "Índice de cobertura vegetal (NDVI médio)", "numerico", "0-1",
           minimo=0.0, maximo=1.0, fonte="MapBiomas / INPE"),
    Coluna("distancia_curso_agua_km", "Distância média da mancha urbana ao curso d'água",
           "numerico", "km", minimo=0.0, maximo=200.0, fonte="ANA"),
]

# --- Condições climáticas do mês de referência ---
NUMERICAS_CLIMA = [
    Coluna("chuva_acumulada_mm", "Chuva acumulada no mês", "numerico", "mm",
           minimo=0.0, maximo=2_000.0, fonte="INMET / CEMADEN"),
    Coluna("chuva_max_24h_mm", "Maior volume de chuva em 24h no mês", "numerico", "mm",
           minimo=0.0, maximo=600.0, fonte="INMET / CEMADEN"),
    Coluna("chuva_max_72h_mm", "Maior volume de chuva em 72h no mês", "numerico", "mm",
           minimo=0.0, maximo=1_000.0, fonte="INMET / CEMADEN"),
    Coluna("dias_com_chuva", "Número de dias com chuva no mês", "numerico", "dias",
           minimo=0.0, maximo=31.0, fonte="INMET"),
    Coluna("anomalia_chuva_percentual",
           "Desvio da chuva em relação à média histórica do mês", "numerico", "%",
           minimo=-100.0, maximo=500.0, fonte="INMET (normais climatológicas)"),
    Coluna("temperatura_media_c", "Temperatura média do mês", "numerico", "°C",
           minimo=-5.0, maximo=45.0, fonte="INMET"),
    Coluna("temperatura_max_c", "Temperatura máxima do mês", "numerico", "°C",
           minimo=0.0, maximo=50.0, fonte="INMET"),
    Coluna("umidade_relativa_media", "Umidade relativa média do ar", "numerico", "%",
           minimo=0.0, maximo=100.0, fonte="INMET"),
    Coluna("umidade_solo_percentual", "Umidade do solo", "numerico", "%",
           minimo=0.0, maximo=100.0, permite_nulo=True, fonte="CEMADEN"),
    Coluna("nivel_rio_m", "Nível do rio na estação mais próxima", "numerico", "m",
           minimo=0.0, maximo=50.0, permite_nulo=True,
           fonte="ANA — HidroWeb (nulo onde não há estação)"),
    Coluna("velocidade_vento_max_kmh", "Velocidade máxima do vento no mês",
           "numerico", "km/h", minimo=0.0, maximo=250.0, fonte="INMET"),
]

# --- Histórico de desastres do município (o coração do S2iD) ---
NUMERICAS_HISTORICO = [
    Coluna("ocorrencias_12m",
           "Ocorrências deste grupo de desastre nos últimos 12 meses",
           "numerico", "registros", minimo=0.0, maximo=100.0, fonte="S2iD"),
    Coluna("ocorrencias_total_historico",
           "Total histórico de ocorrências deste grupo no município",
           "numerico", "registros", minimo=0.0, maximo=1_000.0, fonte="S2iD"),
    Coluna("meses_desde_ultima_ocorrencia",
           "Meses desde a última ocorrência deste grupo (999 = nunca ocorreu)",
           "numerico", "meses", minimo=0.0, maximo=999.0, fonte="S2iD"),
    Coluna("decretos_emergencia_5anos",
           "Decretos de emergência ou calamidade nos últimos 5 anos",
           "numerico", "decretos", minimo=0.0, maximo=50.0, fonte="S2iD"),
    # Os tetos aqui são altos de propósito: as enchentes do RS em 2024
    # afetaram mais de 2 milhões de pessoas, e prejuízos municipais na casa
    # da dezena de bilhões de reais são registrados no S2iD. Um limite
    # apertado rejeitaria justamente os eventos mais graves da base.
    Coluna("media_afetados_historico",
           "Média de pessoas afetadas nas ocorrências passadas",
           "numerico", "pessoas", minimo=0.0, maximo=5_000_000.0, fonte="S2iD"),
    Coluna("danos_materiais_historico_reais",
           "Média de danos materiais declarados nas ocorrências passadas",
           "numerico", "R$", minimo=0.0, maximo=100_000_000_000.0, fonte="S2iD"),
]


NUMERICAS = NUMERICAS_TERRITORIO + NUMERICAS_CLIMA + NUMERICAS_HISTORICO


# --------------------------------------------------------------------------
# Colunas derivadas
# --------------------------------------------------------------------------
# Calculadas automaticamente a partir das colunas acima, no treino e na
# previsão. Não precisam estar no CSV.

DERIVADAS = [
    Coluna("mes_seno", "Componente cíclica do mês (seno)", "numerico",
           minimo=-1.0, maximo=1.0),
    Coluna("mes_cosseno", "Componente cíclica do mês (cosseno)", "numerico",
           minimo=-1.0, maximo=1.0),
    Coluna("intensidade_chuva",
           "Razão entre a chuva máxima em 24h e a acumulada no mês "
           "(quanto maior, mais concentrada foi a chuva)",
           "numerico", minimo=0.0, maximo=1.0),
    Coluna("chuva_por_dia_chuvoso", "Chuva média por dia chuvoso", "numerico", "mm/dia",
           minimo=0.0, maximo=600.0),
    Coluna("ja_ocorreu", "1 se o desastre já ocorreu alguma vez no município", "numerico",
           minimo=0.0, maximo=1.0),
]


# --------------------------------------------------------------------------
# Listas prontas para o pipeline
# --------------------------------------------------------------------------

COLUNAS_NUMERICAS = [c.nome for c in NUMERICAS]
COLUNAS_CATEGORICAS = [c.nome for c in CATEGORICAS]
COLUNAS_DERIVADAS = [c.nome for c in DERIVADAS]
COLUNAS_IDENTIFICACAO = [c.nome for c in IDENTIFICACAO]

# O que o modelo recebe como entrada (na ordem em que o pipeline espera).
# 'mes' entra também como número puro, além das componentes cíclicas.
COLUNAS_MODELO_NUMERICAS = COLUNAS_NUMERICAS + ["mes"] + COLUNAS_DERIVADAS
COLUNAS_MODELO_CATEGORICAS = COLUNAS_CATEGORICAS

# O que o CSV precisa ter, no mínimo.
COLUNAS_OBRIGATORIAS = (
    COLUNAS_IDENTIFICACAO + COLUNAS_CATEGORICAS + COLUNAS_NUMERICAS + [COLUNA_ALVO]
)

# Índice por nome, para consultar faixa/unidade rapidamente.
POR_NOME: dict[str, Coluna] = {
    c.nome: c
    for c in IDENTIFICACAO + CATEGORICAS + NUMERICAS + DERIVADAS
}


def descrever() -> str:
    """Texto legível com o contrato completo. Usado pelo endpoint /esquema."""
    linhas = [
        f"Alvo: {COLUNA_ALVO} -> {', '.join(CLASSES_RISCO)}",
        "",
        f"Identificação ({len(IDENTIFICACAO)} colunas, não entram no modelo):",
    ]
    for c in IDENTIFICACAO:
        linhas.append(f"  - {c.nome}: {c.descricao}")

    for titulo, grupo in [
        ("Categóricas", CATEGORICAS),
        ("Território", NUMERICAS_TERRITORIO),
        ("Clima", NUMERICAS_CLIMA),
        ("Histórico", NUMERICAS_HISTORICO),
        ("Derivadas (calculadas, não precisam estar no CSV)", DERIVADAS),
    ]:
        linhas.append("")
        linhas.append(f"{titulo} ({len(grupo)} colunas):")
        for c in grupo:
            unidade = f" [{c.unidade}]" if c.unidade else ""
            nulo = " (aceita vazio)" if c.permite_nulo else ""
            linhas.append(f"  - {c.nome}{unidade}: {c.descricao}{nulo}")

    return "\n".join(linhas)


if __name__ == "__main__":
    print(descrever())
    print()
    print(f"Total de colunas obrigatórias no CSV: {len(COLUNAS_OBRIGATORIAS)}")
    print(f"Total de features vistas pelo modelo: "
          f"{len(COLUNAS_MODELO_NUMERICAS) + len(COLUNAS_MODELO_CATEGORICAS)} "
          f"(antes do one-hot)")
