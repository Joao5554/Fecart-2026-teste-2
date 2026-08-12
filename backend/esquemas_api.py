"""
Formatos de entrada e saída da API (modelos Pydantic).

Escrever os campos um a um, com faixa e descrição, dá três coisas de graça:
  - a página /docs vira uma documentação navegável, com o significado e a
    unidade de cada variável;
  - o FastAPI rejeita valores absurdos (mês 13, contagem negativa) antes de
    chegarem no modelo;
  - o time do frontend sabe exatamente o que enviar.

As faixas aqui são as mesmas de src/esquema.py — a diferença é que ali elas
validam o CSV do treino, e aqui validam a requisição da API. O teste
testes/test_esquema_api.py garante que as duas listas não saiam de sincronia.
"""

from pydantic import BaseModel, Field

from src import esquema


class EntradaPrevisao(BaseModel):
    """Uma consulta: um município, num mês, para um tipo de desastre."""

    # --- identificação (não entram no modelo, voltam na resposta) ---
    codigo_ibge: int = Field(..., ge=1_000_000, le=9_999_999,
                             description="Código IBGE do município (7 dígitos)")
    municipio: str = Field(..., description="Nome do município")

    # Coordenadas do município. Não entram no modelo: servem apenas para o
    # endpoint /mapa/risco posicionar o ponto. Opcionais porque as previsões
    # em si não precisam delas.
    latitude: float | None = Field(None, ge=-34, le=6, description="Latitude")
    longitude: float | None = Field(None, ge=-74, le=-34, description="Longitude")

    # --- categóricas ---
    uf: str = Field(..., min_length=2, max_length=2, description="Sigla da UF")
    regiao: str = Field(..., description=f"Um de: {', '.join(esquema.REGIOES)}")
    grupo_desastre: str = Field(
        ..., description=f"Um de: {', '.join(esquema.GRUPOS_COBRADE)}"
    )

    # --- tempo ---
    mes: int = Field(..., ge=1, le=12, description="Mês de referência (1 a 12)")

    # --- histórico do município para este tipo de desastre ---
    # Todas contam apenas o que ocorreu ANTES do mês consultado.
    ocorrencias_12m: float = Field(..., ge=0, le=200,
                                   description="Ocorrências nos 12 meses anteriores")
    ocorrencias_24m: float = Field(..., ge=0, le=400,
                                   description="Ocorrências nos 24 meses anteriores")
    ocorrencias_60m: float = Field(..., ge=0, le=800,
                                   description="Ocorrências nos 60 meses anteriores")
    ocorrencias_total_historico: float = Field(
        ..., ge=0, le=2_000, description="Total já registrado no município"
    )
    meses_desde_ultima_ocorrencia: float = Field(
        ..., ge=-1, le=1_200,
        description="Meses desde a última ocorrência (-1 se nunca ocorreu)"
    )
    ja_ocorreu: float = Field(..., ge=0, le=1,
                              description="1 se já ocorreu alguma vez, 0 se nunca")
    anos_de_historico: float = Field(
        ..., ge=0, le=120, description="Anos desde a primeira ocorrência conhecida"
    )
    ocorrencias_mesmo_mes_historico: float = Field(
        ..., ge=0, le=200,
        description="Vezes que já ocorreu neste mesmo mês do calendário"
    )
    reconhecimentos_historico: float = Field(
        ..., ge=0, le=1_000,
        description="Ocorrências anteriores com emergência/calamidade reconhecida"
    )
    mortos_historico: float = Field(..., ge=0, le=100_000,
                                    description="Mortos em ocorrências anteriores")
    afetados_historico: float = Field(..., ge=0, le=100_000_000,
                                      description="Afetados em ocorrências anteriores")
    prejuizo_historico_log: float = Field(
        ..., ge=0, le=30, description="Prejuízo acumulado, em log(1+reais)"
    )

    # --- contexto regional ---
    ocorrencias_municipio_12m: float = Field(
        ..., ge=0, le=500,
        description="Ocorrências de qualquer tipo no município (12 meses)"
    )
    ocorrencias_uf_grupo_12m: float = Field(
        ..., ge=0, le=20_000,
        description="Ocorrências deste tipo em toda a UF (12 meses)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "codigo_ibge": 3303906,
                "municipio": "Petrópolis",
                "uf": "RJ",
                "regiao": "Sudeste",
                "grupo_desastre": "DESLIZAMENTO",
                "mes": 2,
                "ocorrencias_12m": 2,
                "ocorrencias_24m": 3,
                "ocorrencias_60m": 6,
                "ocorrencias_total_historico": 11,
                "meses_desde_ultima_ocorrencia": 4,
                "ja_ocorreu": 1,
                "anos_de_historico": 18.0,
                "ocorrencias_mesmo_mes_historico": 5,
                "reconhecimentos_historico": 7,
                "mortos_historico": 241,
                "afetados_historico": 39_500,
                "prejuizo_historico_log": 17.2,
                "ocorrencias_municipio_12m": 5,
                "ocorrencias_uf_grupo_12m": 48,
            }]
        }
    }


class ConsultaMunicipio(BaseModel):
    """
    Consulta simplificada, usada pela interface.

    Aqui o usuário informa apenas onde, o quê e quando. As quinze variáveis
    históricas são calculadas pelo backend a partir do Atlas — pedir que
    alguém as digitasse à mão tornaria o sistema inutilizável.
    """

    codigo_ibge: int = Field(..., ge=1_000_000, le=9_999_999,
                             description="Código IBGE do município")
    grupo_desastre: str = Field(
        ..., description=f"Um de: {', '.join(esquema.GRUPOS_COBRADE)}"
    )
    mes: int = Field(..., ge=1, le=12, description="Mês a prever (1 a 12)")
    ano: int = Field(2026, ge=1991, le=2100, description="Ano a prever")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "codigo_ibge": 3303906,
                "grupo_desastre": "DESLIZAMENTO",
                "mes": 2,
                "ano": 2026,
            }]
        }
    }


class EntradaLote(BaseModel):
    """Várias consultas de uma vez — é o que o mapa usa para pintar o país."""

    itens: list[EntradaPrevisao] = Field(..., min_length=1, max_length=6_000)


class Previsao(BaseModel):
    """Resultado para uma consulta."""

    codigo_ibge: int
    municipio: str
    grupo_desastre: str
    nivel_risco: str = Field(..., description="baixo, medio ou alto")
    confianca: float = Field(..., description="Probabilidade da classe escolhida (0 a 1)")
    probabilidades: dict[str, float] = Field(
        ..., description="Probabilidade de cada nível de risco"
    )
    cor: str = Field(..., description="Cor sugerida para o mapa (hexadecimal)")


class RespostaPrevisao(BaseModel):
    previsao: Previsao
    modelo_treinado_em: str


class RespostaLote(BaseModel):
    previsoes: list[Previsao]
    total: int
    resumo: dict[str, int] = Field(
        ..., description="Quantos municípios em cada nível de risco"
    )
    modelo_treinado_em: str
