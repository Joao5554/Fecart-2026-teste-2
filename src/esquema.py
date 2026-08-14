"""
Contrato de dados do projeto — fonte única da verdade.

Este arquivo define QUAIS colunas o dataset precisa ter, o tipo de cada uma,
a unidade e a faixa de valores aceita. O treinamento e o backend leem daqui,
então nunca há divergência entre o que o modelo aprendeu e o que a API recebe.

Formato dos dados
-----------------
Uma linha = **um município, em um mês, para um tipo de desastre**.

    codigo_ibge | ano  | mes | grupo_desastre | ... | nivel_risco
    3303906     | 2024 | 2   | DESLIZAMENTO   | ... | alto
    3303906     | 2024 | 2   | INUNDACAO      | ... | medio
    3303906     | 2024 | 3   | DESLIZAMENTO   | ... | baixo

O mesmo município aparece várias vezes: uma por mês e por tipo de desastre.
Isso permite um único modelo cobrir todos os tipos, como no S2iD.

De onde vêm as colunas
----------------------
Todas as variáveis são construídas a partir do **Atlas de Desastres**
(S2iD/SEDEC), pelo módulo `src/atlas.py`. São de três naturezas:

  - **onde**: UF, região e o tipo de desastre em questão;
  - **quando**: o mês, que carrega a sazonalidade;
  - **histórico**: o que já aconteteu naquele município antes do mês previsto.

O Atlas **não traz dados climáticos** (chuva, temperatura, umidade). Quando
essas séries forem obtidas do INMET/CEMADEN, entram como colunas novas aqui
e no ETL — o restante do projeto não precisa mudar.
"""

import hashlib
import json
from dataclasses import dataclass, field

# Versão do contrato de dados. Aumente ao mudar colunas ou classes: serve para
# uma pessoa entender rapidamente que o formato mudou.
# 2.0.0 — troca da base sintética pelo Atlas de Desastres real.
# 3.0.0 — entrada dos dados de chuva do INMET.
VERSAO_ESQUEMA = "3.0.0"


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

# Como o rótulo é construído a partir do que o S2iD registra. Esta é uma
# decisão metodológica do trabalho, não um dado pronto da base.
CRITERIO_ROTULO = {
    "baixo": "Nenhuma ocorrência registrada no município, no mês, para o tipo",
    "medio": "Ocorrência registrada, sem reconhecimento federal e sem mortos",
    "alto": "Ocorrência com mortos ou com reconhecimento de emergência/calamidade",
}


# --------------------------------------------------------------------------
# Grupos de desastre (COBRADE — Codificação Brasileira de Desastres)
# --------------------------------------------------------------------------
# Agrupamento das tipologias do Atlas. O mapeamento tipologia -> grupo está
# em src/atlas.py (TIPOLOGIA_PARA_GRUPO).

GRUPOS_COBRADE = {
    "ESTIAGEM_SECA": "Estiagem e seca",
    "INUNDACAO": "Inundações",
    "ENXURRADA": "Enxurradas",
    "ALAGAMENTO": "Alagamentos",
    "CHUVAS_INTENSAS": "Chuvas intensas",
    "DESLIZAMENTO": "Movimento de massa / deslizamentos",
    "VENDAVAL_CICLONE": "Vendavais, ciclones e tornados",
    "GRANIZO": "Chuvas de granizo",
    "INCENDIO_FLORESTAL": "Incêndio florestal",
    "EROSAO": "Erosão",
}

REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

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
           minimo=1990, maximo=2100, fonte="Atlas de Desastres"),
]


# Colunas categóricas que entram no modelo.
CATEGORICAS = [
    Coluna("uf", "Unidade federativa", "categorico",
           categorias=UFS, fonte="Atlas de Desastres"),
    Coluna("regiao", "Região do país", "categorico",
           categorias=REGIOES, fonte="Atlas de Desastres"),
    Coluna("grupo_desastre", "Tipo de desastre avaliado", "categorico",
           categorias=list(GRUPOS_COBRADE), fonte="Atlas de Desastres (COBRADE)"),
]


# Quando: o mês carrega a sazonalidade (seca tem época, deslizamento também).
NUMERICAS_TEMPO = [
    Coluna("mes", "Mês de referência (1 a 12)", "numerico",
           minimo=1, maximo=12, fonte="Atlas de Desastres"),
]

# Histórico do próprio município para AQUELE tipo de desastre.
# Todas contam apenas o que ocorreu ANTES do mês previsto.
NUMERICAS_HISTORICO = [
    Coluna("ocorrencias_12m", "Ocorrências deste tipo nos 12 meses anteriores",
           "numerico", unidade="ocorrências", minimo=0, maximo=200,
           fonte="Atlas de Desastres"),
    Coluna("ocorrencias_24m", "Ocorrências deste tipo nos 24 meses anteriores",
           "numerico", unidade="ocorrências", minimo=0, maximo=400,
           fonte="Atlas de Desastres"),
    Coluna("ocorrencias_60m", "Ocorrências deste tipo nos 60 meses anteriores",
           "numerico", unidade="ocorrências", minimo=0, maximo=800,
           fonte="Atlas de Desastres"),
    Coluna("ocorrencias_total_historico",
           "Total de ocorrências deste tipo já registradas no município",
           "numerico", unidade="ocorrências", minimo=0, maximo=2000,
           fonte="Atlas de Desastres"),
    Coluna("meses_desde_ultima_ocorrencia",
           "Meses desde a última ocorrência deste tipo (-1 se nunca ocorreu)",
           "numerico", unidade="meses", minimo=-1, maximo=1200,
           fonte="Atlas de Desastres"),
    Coluna("ja_ocorreu", "1 se este tipo já ocorreu alguma vez no município",
           "numerico", minimo=0, maximo=1, fonte="Atlas de Desastres"),
    Coluna("anos_de_historico",
           "Anos decorridos desde a primeira ocorrência conhecida",
           "numerico", unidade="anos", minimo=0, maximo=120,
           fonte="Atlas de Desastres"),
    Coluna("ocorrencias_mesmo_mes_historico",
           "Vezes que este tipo já ocorreu neste mesmo mês do calendário",
           "numerico", unidade="ocorrências", minimo=0, maximo=200,
           fonte="Atlas de Desastres"),
    Coluna("reconhecimentos_historico",
           "Ocorrências anteriores com reconhecimento de emergência/calamidade",
           "numerico", unidade="ocorrências", minimo=0, maximo=1000,
           fonte="Atlas de Desastres"),
    Coluna("mortos_historico", "Total de mortos em ocorrências anteriores",
           "numerico", unidade="pessoas", minimo=0, maximo=100_000,
           fonte="Atlas de Desastres"),
    Coluna("afetados_historico", "Total de afetados em ocorrências anteriores",
           "numerico", unidade="pessoas", minimo=0, maximo=100_000_000,
           fonte="Atlas de Desastres"),
    Coluna("prejuizo_historico_log",
           "Prejuízo acumulado em ocorrências anteriores, em log(1+reais)",
           "numerico", unidade="log(R$)", minimo=0, maximo=30,
           fonte="Atlas de Desastres"),
]

# Contexto: o que acontece em volta do município.
NUMERICAS_CONTEXTO = [
    Coluna("ocorrencias_municipio_12m",
           "Ocorrências de qualquer tipo no município nos 12 meses anteriores",
           "numerico", unidade="ocorrências", minimo=0, maximo=500,
           fonte="Atlas de Desastres"),
    Coluna("ocorrencias_uf_grupo_12m",
           "Ocorrências deste tipo em toda a UF nos 12 meses anteriores",
           "numerico", unidade="ocorrências", minimo=0, maximo=20_000,
           fonte="Atlas de Desastres"),
]

# Clima do INMET. Todas se referem aos meses ANTERIORES ao mês previsto — a
# chuva do próprio mês não pode entrar, senão o modelo estaria descrevendo o
# que já aconteceu em vez de prever.
#
# Aceitam vazio de propósito: cerca de um quarto das linhas não alcança nenhuma
# estação com medição naquele mês, e forçar um valor ali inventaria dado.
NUMERICAS_CLIMA = [
    Coluna("chuva_mes_anterior_mm", "Chuva acumulada no mês anterior",
           "numerico", unidade="mm", minimo=0, maximo=3000,
           permite_nulo=True, fonte="INMET"),
    Coluna("chuva_max_dia_mes_anterior_mm",
           "Maior chuva em um único dia do mês anterior", "numerico",
           unidade="mm", minimo=0, maximo=800, permite_nulo=True, fonte="INMET"),
    Coluna("dias_com_chuva_mes_anterior",
           "Dias com chuva no mês anterior", "numerico", unidade="dias",
           minimo=0, maximo=31, permite_nulo=True, fonte="INMET"),
    Coluna("chuva_3_meses_anteriores_mm",
           "Chuva acumulada nos três meses anteriores (solo saturado)",
           "numerico", unidade="mm", minimo=0, maximo=9000,
           permite_nulo=True, fonte="INMET"),
    Coluna("anomalia_chuva_pct",
           "Quanto a chuva do mês anterior fugiu do normal daquele lugar",
           "numerico", unidade="%", minimo=-100, maximo=500,
           permite_nulo=True, fonte="INMET (normal de 2000–2009)"),
    Coluna("temperatura_mes_anterior_c", "Temperatura média do mês anterior",
           "numerico", unidade="°C", minimo=-10, maximo=50,
           permite_nulo=True, fonte="INMET"),
    Coluna("umidade_mes_anterior_pct", "Umidade relativa média do mês anterior",
           "numerico", unidade="%", minimo=0, maximo=100,
           permite_nulo=True, fonte="INMET"),
    Coluna("rajada_mes_anterior_kmh", "Maior rajada de vento do mês anterior",
           "numerico", unidade="km/h", minimo=0, maximo=250,
           permite_nulo=True, fonte="INMET"),
    Coluna("meses_de_clima_disponiveis",
           "Quantos dos três meses anteriores têm medição (0 a 3)",
           "numerico", minimo=0, maximo=3, fonte="INMET"),
]

NUMERICAS = (NUMERICAS_TEMPO + NUMERICAS_HISTORICO + NUMERICAS_CONTEXTO
             + NUMERICAS_CLIMA)


# Colunas calculadas pelo pipeline a partir das anteriores.
# Não precisam existir no CSV: src/caracteristicas.py as cria.
DERIVADAS = [
    Coluna("mes_seno", "Componente cíclica do mês (seno)", "numerico",
           minimo=-1, maximo=1),
    Coluna("mes_cosseno", "Componente cíclica do mês (cosseno)", "numerico",
           minimo=-1, maximo=1),
    Coluna("ocorrencias_por_ano",
           "Frequência média de ocorrências por ano de histórico", "numerico",
           minimo=0, maximo=200),
    Coluna("proporcao_reconhecidas",
           "Fração das ocorrências anteriores que viraram emergência oficial",
           "numerico", minimo=0, maximo=1),
    Coluna("gravidade_media_historica",
           "Afetados por ocorrência anterior (mede o porte típico do evento)",
           "numerico", minimo=0, maximo=10_000_000),
]


# --------------------------------------------------------------------------
# Listas prontas para o pipeline
# --------------------------------------------------------------------------

COLUNAS_NUMERICAS = [c.nome for c in NUMERICAS]
# Preenchidas por src/clima.py, não pelo ETL do Atlas.
COLUNAS_CLIMA = [c.nome for c in NUMERICAS_CLIMA]
COLUNAS_CATEGORICAS = [c.nome for c in CATEGORICAS]
COLUNAS_DERIVADAS = [c.nome for c in DERIVADAS]
COLUNAS_IDENTIFICACAO = [c.nome for c in IDENTIFICACAO]

# O que o modelo recebe como entrada (na ordem em que o pipeline espera).
COLUNAS_MODELO_NUMERICAS = COLUNAS_NUMERICAS + COLUNAS_DERIVADAS
COLUNAS_MODELO_CATEGORICAS = COLUNAS_CATEGORICAS

# O que identifica uma linha de forma única. Duas linhas com a mesma chave
# são repetição, e repetição dá peso extra àquele caso no treino.
CHAVE_LINHA = ["codigo_ibge", "ano", "mes", "grupo_desastre"]

# O que o CSV precisa ter, no mínimo.
COLUNAS_OBRIGATORIAS = (
    COLUNAS_IDENTIFICACAO + COLUNAS_CATEGORICAS + COLUNAS_NUMERICAS + [COLUNA_ALVO]
)

# Índice por nome, para consultar faixa/unidade rapidamente.
POR_NOME: dict[str, Coluna] = {
    c.nome: c
    for c in IDENTIFICACAO + CATEGORICAS + NUMERICAS + DERIVADAS
}


def assinatura() -> str:
    """
    Impressão digital do contrato de dados.

    Resume, em um hash curto, tudo que o modelo precisa enxergar: o alvo, as
    classes e as colunas de entrada. O treinamento grava esta assinatura nos
    metadados e a API confere na hora de carregar o modelo.

    Serve para pegar o erro silencioso mais chato do projeto: alguém altera as
    colunas em src/esquema.py, dá `git pull` sem retreinar, e o modelo antigo
    continua respondendo — com previsões que não significam mais nada.
    Diferente de um número de versão, esta assinatura não depende de ninguém
    lembrar de atualizá-la.
    """
    contrato = {
        "alvo": COLUNA_ALVO,
        "classes": list(CLASSES_RISCO),
        "numericas": list(COLUNAS_MODELO_NUMERICAS),
        "categoricas": list(COLUNAS_MODELO_CATEGORICAS),
    }
    texto = json.dumps(contrato, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def descrever() -> str:
    """Texto legível com o contrato completo. Usado pelo endpoint /esquema."""
    linhas = [
        f"Alvo: {COLUNA_ALVO} -> {', '.join(CLASSES_RISCO)}",
        "",
        "Como o rótulo é definido:",
    ]
    for classe, criterio in CRITERIO_ROTULO.items():
        linhas.append(f"  - {classe}: {criterio}")

    linhas += ["", f"Identificação ({len(IDENTIFICACAO)} colunas, não entram no modelo):"]
    for c in IDENTIFICACAO:
        linhas.append(f"  - {c.nome}: {c.descricao}")

    for titulo, grupo in [
        ("Categóricas", CATEGORICAS),
        ("Tempo", NUMERICAS_TEMPO),
        ("Histórico do município", NUMERICAS_HISTORICO),
        ("Contexto regional", NUMERICAS_CONTEXTO),
        ("Clima do INMET (sempre de meses anteriores)", NUMERICAS_CLIMA),
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
    print(f"Assinatura do contrato: {assinatura()}")
