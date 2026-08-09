"""
Esquema (contrato) dos dados do projeto.

Este arquivo é a ÚNICA fonte da verdade sobre:
  - quais colunas o modelo usa como entrada;
  - qual coluna é o alvo (o que queremos prever);
  - quais valores são válidos em cada coluna;
  - onde ficam os arquivos de dados e do modelo.

Quando a base histórica real de desastres naturais do Brasil chegar,
o ajuste é feito AQUI. O treinamento, a API e os testes leem tudo daqui,
então nada mais precisa ser alterado em vários lugares.
"""

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent

DIR_DADOS = RAIZ / "dados"
DIR_DADOS_EXEMPLO = DIR_DADOS / "exemplo"
DIR_DADOS_BRUTO = DIR_DADOS / "bruto"
DIR_MODELOS = RAIZ / "modelos"

# Dados sintéticos usados enquanto a base real não existe.
ARQUIVO_DADOS_EXEMPLO = DIR_DADOS_EXEMPLO / "ocorrencias_sinteticas.csv"

# Quando a base real chegar, coloque o CSV em dados/bruto/ com este nome
# (ou mude o nome aqui). O treinamento prefere a base real automaticamente.
ARQUIVO_DADOS_REAL = DIR_DADOS_BRUTO / "ocorrencias.csv"

ARQUIVO_MODELO = DIR_MODELOS / "modelo.pkl"
ARQUIVO_METADADOS = DIR_MODELOS / "modelo_metadados.json"


def caminho_dados() -> tuple[Path, str]:
    """
    Decide qual base usar: a real, se existir; senão, a sintética.

    Retorna o caminho do arquivo e a origem ("real" ou "sintetico"),
    que fica registrada nos metadados do modelo.
    """
    if ARQUIVO_DADOS_REAL.exists():
        return ARQUIVO_DADOS_REAL, "real"
    return ARQUIVO_DADOS_EXEMPLO, "sintetico"


# ---------------------------------------------------------------------------
# Definição das colunas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Coluna:
    """Descreve uma coluna de entrada do modelo."""

    nome: str
    tipo: str  # "numerica" ou "categorica"
    descricao: str
    unidade: str = ""
    minimo: float | None = None
    maximo: float | None = None
    categorias: tuple[str, ...] = field(default_factory=tuple)
    exemplo: float | str | None = None


REGIOES = ("Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul")

UFS = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
)

BIOMAS = ("Amazonia", "Caatinga", "Cerrado", "Mata Atlantica", "Pampa", "Pantanal")

# Ordem das colunas importa: é a ordem usada no DataFrame de entrada do modelo.
COLUNAS: tuple[Coluna, ...] = (
    Coluna(
        nome="uf",
        tipo="categorica",
        descricao="Unidade federativa (sigla do estado)",
        categorias=UFS,
        exemplo="SP",
    ),
    Coluna(
        nome="regiao",
        tipo="categorica",
        descricao="Região do país",
        categorias=REGIOES,
        exemplo="Sudeste",
    ),
    Coluna(
        nome="bioma",
        tipo="categorica",
        descricao="Bioma predominante no município",
        categorias=BIOMAS,
        exemplo="Mata Atlantica",
    ),
    Coluna(
        nome="mes",
        tipo="numerica",
        descricao="Mês de referência da observação",
        minimo=1,
        maximo=12,
        exemplo=1,
    ),
    Coluna(
        nome="precipitacao_mm",
        tipo="numerica",
        descricao="Chuva acumulada no mês",
        unidade="mm",
        minimo=0,
        maximo=1500,
        exemplo=320.5,
    ),
    Coluna(
        nome="precipitacao_max_24h_mm",
        tipo="numerica",
        descricao="Maior volume de chuva registrado em 24 horas no mês",
        unidade="mm",
        minimo=0,
        maximo=400,
        exemplo=85.2,
    ),
    Coluna(
        nome="dias_com_chuva",
        tipo="numerica",
        descricao="Número de dias com chuva no mês",
        unidade="dias",
        minimo=0,
        maximo=31,
        exemplo=18,
    ),
    Coluna(
        nome="temperatura_media_c",
        tipo="numerica",
        descricao="Temperatura média do mês",
        unidade="°C",
        minimo=-5,
        maximo=45,
        exemplo=24.3,
    ),
    Coluna(
        nome="umidade_relativa_pct",
        tipo="numerica",
        descricao="Umidade relativa média do ar",
        unidade="%",
        minimo=0,
        maximo=100,
        exemplo=78.0,
    ),
    Coluna(
        nome="rajada_vento_max_kmh",
        tipo="numerica",
        descricao="Velocidade da maior rajada de vento registrada no mês",
        unidade="km/h",
        minimo=0,
        maximo=180,
        exemplo=52.0,
    ),
    Coluna(
        nome="altitude_m",
        tipo="numerica",
        descricao="Altitude média do município",
        unidade="m",
        minimo=0,
        maximo=3000,
        exemplo=760.0,
    ),
    Coluna(
        nome="declividade_media_pct",
        tipo="numerica",
        descricao="Declividade média do terreno (relevante para deslizamentos)",
        unidade="%",
        minimo=0,
        maximo=60,
        exemplo=12.5,
    ),
    Coluna(
        nome="densidade_demografica_hab_km2",
        tipo="numerica",
        descricao="Densidade demográfica do município",
        unidade="hab/km²",
        minimo=0,
        maximo=15000,
        exemplo=2100.0,
    ),
    Coluna(
        nome="pct_area_urbana",
        tipo="numerica",
        descricao="Percentual do território do município que é área urbana",
        unidade="%",
        minimo=0,
        maximo=100,
        exemplo=45.0,
    ),
    Coluna(
        nome="indice_vegetacao_ndvi",
        tipo="numerica",
        descricao="Índice de vegetação NDVI (0 = solo exposto, 1 = vegetação densa)",
        minimo=0,
        maximo=1,
        exemplo=0.62,
    ),
)

# ---------------------------------------------------------------------------
# Alvo (o que o modelo prevê)
# ---------------------------------------------------------------------------

COLUNA_ALVO = "tipo_desastre"

# Classes agrupadas a partir da classificação COBRADE usada pela Defesa Civil.
CLASSES = (
    "nenhum",
    "estiagem_seca",
    "inundacao",
    "deslizamento",
    "tempestade",
    "incendio_florestal",
)

DESCRICAO_CLASSES = {
    "nenhum": "Nenhum desastre relevante registrado no período",
    "estiagem_seca": "Estiagem ou seca prolongada",
    "inundacao": "Inundação, enxurrada ou alagamento",
    "deslizamento": "Movimento de massa / deslizamento de encosta",
    "tempestade": "Tempestade, vendaval ou granizo",
    "incendio_florestal": "Incêndio florestal",
}

# ---------------------------------------------------------------------------
# Atalhos usados pelo restante do projeto
# ---------------------------------------------------------------------------

COLUNAS_NUMERICAS: tuple[str, ...] = tuple(
    c.nome for c in COLUNAS if c.tipo == "numerica"
)
COLUNAS_CATEGORICAS: tuple[str, ...] = tuple(
    c.nome for c in COLUNAS if c.tipo == "categorica"
)
NOMES_COLUNAS: tuple[str, ...] = tuple(c.nome for c in COLUNAS)
COLUNAS_POR_NOME: dict[str, Coluna] = {c.nome: c for c in COLUNAS}


def exemplo_entrada() -> dict[str, float | str]:
    """Uma linha de entrada válida, usada na documentação da API e nos testes."""
    return {c.nome: c.exemplo for c in COLUNAS}
