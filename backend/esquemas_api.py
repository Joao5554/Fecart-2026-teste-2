"""
Formatos de entrada e saída da API (modelos Pydantic).

Escrever os campos um a um, com faixa e descrição, dá três coisas de graça:
  - a página /docs vira uma documentação navegável, com o significado e a
    unidade de cada variável;
  - o FastAPI rejeita valores absurdos (chuva negativa, mês 13) antes de
    chegarem no modelo;
  - o time do frontend sabe exatamente o que enviar.

As faixas aqui são as mesmas de src/esquema.py — a diferença é que ali elas
validam o CSV do treino, e aqui validam a requisição da API.
"""

from pydantic import BaseModel, Field

from src import esquema


class EntradaPrevisao(BaseModel):
    """Uma linha de consulta: um município, num mês, para um tipo de desastre."""

    # --- identificação (não entram no modelo, voltam na resposta) ---
    codigo_ibge: int = Field(..., ge=1_000_000, le=9_999_999,
                             description="Código IBGE do município (7 dígitos)")
    municipio: str = Field(..., description="Nome do município")
    mes: int = Field(..., ge=1, le=12, description="Mês de referência (1 a 12)")

    # --- categóricas ---
    uf: str = Field(..., min_length=2, max_length=2, description="Sigla da UF")
    regiao: str = Field(..., description=f"Uma de: {', '.join(esquema.REGIOES)}")
    bioma: str = Field(..., description=f"Um de: {', '.join(esquema.BIOMAS)}")
    cobrade_grupo: str = Field(
        ..., description=f"Tipo de desastre. Um de: {', '.join(esquema.GRUPOS_COBRADE)}"
    )

    # --- território ---
    latitude: float = Field(..., ge=-34, le=6, description="Latitude do município")
    longitude: float = Field(..., ge=-74, le=-34, description="Longitude do município")
    area_km2: float = Field(..., ge=1, le=200_000, description="Área territorial (km²)")
    populacao: float = Field(..., ge=0, le=15_000_000, description="População estimada")
    densidade_demografica: float = Field(..., ge=0, le=15_000,
                                         description="Densidade demográfica (hab/km²)")
    altitude_media_m: float = Field(..., ge=-10, le=3_000,
                                    description="Altitude média (m)")
    declividade_media_graus: float = Field(..., ge=0, le=60,
                                           description="Declividade média do terreno (graus)")
    percentual_area_urbana: float = Field(..., ge=0, le=100,
                                          description="Percentual de área urbanizada")
    percentual_domicilios_area_risco: float = Field(
        ..., ge=0, le=100, description="Percentual de domicílios em área de risco"
    )
    indice_vegetacao: float = Field(..., ge=0, le=1,
                                    description="Cobertura vegetal (NDVI médio, 0 a 1)")
    distancia_curso_agua_km: float = Field(..., ge=0, le=200,
                                           description="Distância ao curso d'água (km)")

    # --- clima do período consultado ---
    chuva_acumulada_mm: float = Field(..., ge=0, le=2_000,
                                      description="Chuva acumulada no mês (mm)")
    chuva_max_24h_mm: float = Field(..., ge=0, le=600,
                                    description="Maior chuva em 24h no mês (mm)")
    chuva_max_72h_mm: float = Field(..., ge=0, le=1_000,
                                    description="Maior chuva em 72h no mês (mm)")
    dias_com_chuva: float = Field(..., ge=0, le=31,
                                  description="Dias com chuva no mês")
    anomalia_chuva_percentual: float = Field(
        ..., ge=-100, le=500,
        description="Desvio da chuva em relação à média histórica do mês (%)"
    )
    temperatura_media_c: float = Field(..., ge=-5, le=45,
                                       description="Temperatura média do mês (°C)")
    temperatura_max_c: float = Field(..., ge=0, le=50,
                                     description="Temperatura máxima do mês (°C)")
    umidade_relativa_media: float = Field(..., ge=0, le=100,
                                          description="Umidade relativa média do ar (%)")
    velocidade_vento_max_kmh: float = Field(..., ge=0, le=250,
                                            description="Vento máximo no mês (km/h)")

    # Estes dois podem faltar de verdade: nem todo município tem sensor de solo
    # do CEMADEN nem estação fluviométrica da ANA. O modelo preenche sozinho.
    umidade_solo_percentual: float | None = Field(
        None, ge=0, le=100,
        description="Umidade do solo (%). Deixe vazio se não houver sensor."
    )
    nivel_rio_m: float | None = Field(
        None, ge=0, le=50,
        description="Nível do rio (m). Deixe vazio se não houver estação."
    )

    # --- histórico do S2iD ---
    ocorrencias_12m: float = Field(..., ge=0, le=100,
                                   description="Ocorrências deste tipo nos últimos 12 meses")
    ocorrencias_total_historico: float = Field(
        ..., ge=0, le=1_000, description="Total histórico de ocorrências deste tipo"
    )
    meses_desde_ultima_ocorrencia: float = Field(
        ..., ge=0, le=999,
        description="Meses desde a última ocorrência (use 999 se nunca ocorreu)"
    )
    decretos_emergencia_5anos: float = Field(
        ..., ge=0, le=50, description="Decretos de emergência nos últimos 5 anos"
    )
    media_afetados_historico: float = Field(
        ..., ge=0, le=5_000_000, description="Média de afetados nas ocorrências passadas"
    )
    danos_materiais_historico_reais: float = Field(
        ..., ge=0, le=100_000_000_000,
        description="Média de danos materiais nas ocorrências passadas (R$)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "codigo_ibge": 3303906,
                "municipio": "Petropolis",
                "mes": 2,
                "uf": "RJ",
                "regiao": "Sudeste",
                "bioma": "Mata Atlantica",
                "cobrade_grupo": "DESLIZAMENTO",
                "latitude": -22.51,
                "longitude": -43.18,
                "area_km2": 796,
                "populacao": 307144,
                "densidade_demografica": 385.9,
                "altitude_media_m": 809,
                "declividade_media_graus": 24.0,
                "percentual_area_urbana": 92.0,
                "percentual_domicilios_area_risco": 12.5,
                "indice_vegetacao": 0.42,
                "distancia_curso_agua_km": 0.8,
                "chuva_acumulada_mm": 412.0,
                "chuva_max_24h_mm": 258.0,
                "chuva_max_72h_mm": 390.0,
                "dias_com_chuva": 18,
                "anomalia_chuva_percentual": 75.0,
                "temperatura_media_c": 23.5,
                "temperatura_max_c": 33.0,
                "umidade_relativa_media": 88.0,
                "velocidade_vento_max_kmh": 34.0,
                "umidade_solo_percentual": 82.0,
                "nivel_rio_m": 3.4,
                "ocorrencias_12m": 2,
                "ocorrencias_total_historico": 19,
                "meses_desde_ultima_ocorrencia": 4,
                "decretos_emergencia_5anos": 3,
                "media_afetados_historico": 1850.0,
                "danos_materiais_historico_reais": 4200000.0,
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
    cobrade_grupo: str
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
