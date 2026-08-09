"""
Esquemas de entrada e saída da API (modelos Pydantic).

As faixas de valores e as categorias válidas são conferidas contra
treinamento/esquema.py, que continua sendo a fonte da verdade do projeto.
O teste testes/test_esquema.py garante que os dois nunca saiam de sincronia.
"""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from treinamento.esquema import COLUNAS_POR_NOME, exemplo_entrada


class Observacao(BaseModel):
    """Condições climáticas e geográficas de um município em um mês."""

    uf: str = Field(description="Sigla do estado (ex.: SP, RJ, BA)")
    regiao: str = Field(description="Norte, Nordeste, Centro-Oeste, Sudeste ou Sul")
    bioma: str = Field(description="Bioma predominante no município")

    mes: Annotated[int, Field(ge=1, le=12, description="Mês de referência (1 a 12)")]
    precipitacao_mm: Annotated[float, Field(ge=0, le=1500, description="Chuva acumulada no mês (mm)")]
    precipitacao_max_24h_mm: Annotated[float, Field(ge=0, le=400, description="Maior chuva em 24h no mês (mm)")]
    dias_com_chuva: Annotated[int, Field(ge=0, le=31, description="Dias com chuva no mês")]
    temperatura_media_c: Annotated[float, Field(ge=-5, le=45, description="Temperatura média (°C)")]
    umidade_relativa_pct: Annotated[float, Field(ge=0, le=100, description="Umidade relativa média (%)")]
    rajada_vento_max_kmh: Annotated[float, Field(ge=0, le=180, description="Maior rajada de vento (km/h)")]
    altitude_m: Annotated[float, Field(ge=0, le=3000, description="Altitude média (m)")]
    declividade_media_pct: Annotated[float, Field(ge=0, le=60, description="Declividade média do terreno (%)")]
    densidade_demografica_hab_km2: Annotated[float, Field(ge=0, le=15000, description="Densidade demográfica (hab/km²)")]
    pct_area_urbana: Annotated[float, Field(ge=0, le=100, description="Percentual de área urbana (%)")]
    indice_vegetacao_ndvi: Annotated[float, Field(ge=0, le=1, description="Índice de vegetação NDVI (0 a 1)")]

    model_config = {"json_schema_extra": {"examples": [exemplo_entrada()]}}

    @field_validator("uf", "regiao", "bioma")
    @classmethod
    def _validar_categoria(cls, valor: str, info) -> str:
        """Confere o valor contra a lista de categorias do esquema do projeto."""
        categorias = COLUNAS_POR_NOME[info.field_name].categorias
        if valor not in categorias:
            raise ValueError(
                f"valor '{valor}' inválido. Use um destes: {', '.join(categorias)}"
            )
        return valor


class Previsao(BaseModel):
    """Resultado da previsão para uma observação."""

    tipo_desastre_previsto: str = Field(description="Classe com maior probabilidade")
    descricao: str = Field(description="Descrição do tipo de desastre em português")
    confianca: float = Field(description="Probabilidade da classe prevista (0 a 1)")
    probabilidade_algum_desastre: float = Field(
        description="Probabilidade de ocorrer qualquer desastre (1 - probabilidade de 'nenhum')"
    )
    nivel_risco: str = Field(description="baixo, moderado, alto ou muito_alto")
    probabilidades: dict[str, float] = Field(
        description="Probabilidade estimada para cada classe"
    )


class RespostaLote(BaseModel):
    """Resultado de uma previsão em lote."""

    total: int
    previsoes: list[Previsao]


class InfoModelo(BaseModel):
    """Metadados do modelo carregado na memória."""

    modelo_carregado: bool
    versao_modelo: str | None = None
    treinado_em: str | None = None
    origem_dados: str | None = None
    aviso: str | None = None
    classes: list[str] = []
    metricas: dict[str, float] = {}
    importancia_variaveis: dict[str, float] = {}
    ambiente_treino: dict[str, str] = {}
