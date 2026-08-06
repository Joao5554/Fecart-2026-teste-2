"""
API que serve as previsões de risco de desastres naturais.

Como executar (a partir da raiz do projeto):
    uvicorn backend.app:app --reload

Depois abra http://127.0.0.1:8000/docs para testar tudo pelo navegador.

Endpoints:
    GET  /                     estado da API e do modelo
    GET  /esquema              contrato de dados (quais campos enviar)
    GET  /modelo/info          métricas e metadados do modelo carregado
    POST /modelo/recarregar    recarrega o .pkl sem reiniciar o servidor
    POST /prever               previsão para um município
    POST /prever/lote          previsão para vários municípios de uma vez
    POST /mapa/risco           GeoJSON pronto para o mapa interativo
"""

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.esquemas_api import (  # noqa: E402
    EntradaLote,
    EntradaPrevisao,
    Previsao,
    RespostaLote,
    RespostaPrevisao,
)
from src import caracteristicas, esquema  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_MODELO = RAIZ / "modelo" / "modelo.pkl"
ARQUIVO_METADADOS = RAIZ / "modelo" / "metadados.json"

MENSAGEM_SEM_MODELO = (
    "O modelo ainda não foi treinado. Rode, a partir da raiz do projeto:\n"
    "  python dados/gerar_dados_sinteticos.py   (se ainda não tiver a base real)\n"
    "  python treinamento/treinar_modelo.py"
)


app = FastAPI(
    title="API — Previsão de Risco de Desastres Naturais",
    description=(
        "Prevê o nível de risco (baixo, médio ou alto) de desastres naturais "
        "por município brasileiro, a partir de dados históricos do S2iD "
        "(Defesa Civil) combinados com dados climáticos e territoriais."
    ),
    version="0.2.0",
)

# Libera o acesso a partir do frontend do mapa, que roda em outra porta.
# Em produção, troque ["*"] pela URL real do frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Carregamento do modelo
# --------------------------------------------------------------------------

modelo = None
metadados: dict = {}


def carregar_modelo() -> bool:
    """Carrega o modelo e os metadados do disco. Devolve True se conseguiu."""
    global modelo, metadados

    if not ARQUIVO_MODELO.exists():
        modelo, metadados = None, {}
        return False

    modelo = joblib.load(ARQUIVO_MODELO)
    metadados = (
        json.loads(ARQUIVO_METADADOS.read_text(encoding="utf-8"))
        if ARQUIVO_METADADOS.exists() else {}
    )
    return True


# Carrega uma única vez, quando o servidor sobe. Carregar a cada requisição
# gastaria segundos por chamada.
carregar_modelo()


def exigir_modelo():
    """Devolve o modelo ou responde 503 com instruções claras."""
    if modelo is None:
        raise HTTPException(status_code=503, detail=MENSAGEM_SEM_MODELO)
    return modelo


def _prever_muitos(entradas: list[EntradaPrevisao]) -> list[Previsao]:
    """Roda o modelo em várias linhas de uma vez.

    Uma chamada com N linhas é muito mais rápida que N chamadas de 1 linha —
    é por isso que o endpoint de lote existe.
    """
    modelo_ativo = exigir_modelo()

    dados = pd.DataFrame([e.model_dump() for e in entradas])
    X = caracteristicas.preparar_para_previsao(dados)

    classes = list(modelo_ativo.classes_)
    probabilidades = modelo_ativo.predict_proba(X)

    resultados = []
    for entrada, linha in zip(entradas, probabilidades):
        por_classe = {c: float(p) for c, p in zip(classes, linha)}
        # Ordena na ordem baixo -> medio -> alto, que é mais legível no frontend
        # do que a ordem alfabética que o sklearn usa internamente.
        por_classe = {
            c: round(por_classe.get(c, 0.0), 4) for c in esquema.CLASSES_RISCO
        }
        nivel = max(por_classe, key=por_classe.get)

        resultados.append(Previsao(
            codigo_ibge=entrada.codigo_ibge,
            municipio=entrada.municipio,
            cobrade_grupo=entrada.cobrade_grupo,
            nivel_risco=nivel,
            confianca=por_classe[nivel],
            probabilidades=por_classe,
            cor=esquema.CORES_RISCO[nivel],
        ))

    return resultados


def _treinado_em() -> str:
    return metadados.get("treinado_em", "desconhecido")


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/", tags=["status"])
def raiz():
    """Estado da API. Serve como health check."""
    return {
        "status": "ok",
        "modelo_carregado": modelo is not None,
        "mensagem": None if modelo else MENSAGEM_SEM_MODELO,
        "treinado_em": _treinado_em() if modelo else None,
        "niveis_de_risco": esquema.CLASSES_RISCO,
        "tipos_de_desastre": list(esquema.GRUPOS_COBRADE),
        "documentacao": "/docs",
    }


@app.get("/esquema", tags=["status"])
def ver_esquema():
    """Descreve todos os campos esperados: significado, unidade e faixa."""
    return {
        "alvo": esquema.COLUNA_ALVO,
        "classes": esquema.CLASSES_RISCO,
        "tipos_de_desastre": esquema.GRUPOS_COBRADE,
        "campos": [
            {
                "nome": c.nome,
                "descricao": c.descricao,
                "tipo": c.tipo,
                "unidade": c.unidade,
                "minimo": c.minimo,
                "maximo": c.maximo,
                "aceita_vazio": c.permite_nulo,
                "fonte": c.fonte,
            }
            for c in esquema.CATEGORICAS + esquema.NUMERICAS
        ],
        "texto": esquema.descrever(),
    }


@app.get("/modelo/info", tags=["modelo"])
def info_modelo():
    """Métricas, período coberto e variáveis mais importantes do modelo."""
    exigir_modelo()
    if not metadados:
        return {"aviso": "modelo carregado, mas sem arquivo de metadados"}

    return {
        "treinado_em": metadados.get("treinado_em"),
        "linhas_de_treino": metadados.get("linhas_totais"),
        "municipios": metadados.get("municipios"),
        "periodo": metadados.get("periodo"),
        "tipos_de_desastre": metadados.get("grupos_cobrade"),
        "distribuicao_classes": metadados.get("distribuicao_classes"),
        "metricas": {
            k: v for k, v in metadados.get("metricas", {}).items()
            if k != "relatorio_por_classe"
        },
        "desempenho_por_classe": (
            metadados.get("metricas", {}).get("relatorio_por_classe")
        ),
        "validacao_cruzada": metadados.get("validacao_cruzada"),
        "variaveis_mais_importantes": dict(
            list(metadados.get("importancia_variaveis", {}).items())[:10]
        ),
        "versoes": metadados.get("versoes"),
    }


@app.post("/modelo/recarregar", tags=["modelo"])
def recarregar():
    """Recarrega o .pkl do disco, útil depois de treinar de novo.

    Evita ter que derrubar e subir o servidor a cada retreino.
    """
    if carregar_modelo():
        return {"status": "modelo recarregado", "treinado_em": _treinado_em()}
    raise HTTPException(status_code=404, detail=MENSAGEM_SEM_MODELO)


@app.post("/prever", response_model=RespostaPrevisao, tags=["previsao"])
def prever(entrada: EntradaPrevisao):
    """Prevê o nível de risco para um município, num mês, para um tipo de desastre."""
    previsao = _prever_muitos([entrada])[0]
    return RespostaPrevisao(previsao=previsao, modelo_treinado_em=_treinado_em())


@app.post("/prever/lote", response_model=RespostaLote, tags=["previsao"])
def prever_lote(entrada: EntradaLote):
    """Prevê o risco para vários municípios de uma vez."""
    previsoes = _prever_muitos(entrada.itens)

    resumo = {classe: 0 for classe in esquema.CLASSES_RISCO}
    for p in previsoes:
        resumo[p.nivel_risco] += 1

    return RespostaLote(
        previsoes=previsoes,
        total=len(previsoes),
        resumo=resumo,
        modelo_treinado_em=_treinado_em(),
    )


@app.post("/mapa/risco", tags=["mapa"])
def mapa_risco(entrada: EntradaLote):
    """Devolve as previsões como GeoJSON, pronto para o mapa interativo.

    O formato é o padrão que Leaflet, Mapbox e OpenLayers consomem
    diretamente — o frontend só precisa jogar o resultado na camada do mapa,
    usando `properties.cor` para pintar cada ponto.
    """
    previsoes = _prever_muitos(entrada.itens)

    feicoes = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                # GeoJSON usa a ordem [longitude, latitude] — o inverso do
                # que a maioria das pessoas espera. Trocar aqui joga o ponto
                # no meio do oceano.
                "coordinates": [item.longitude, item.latitude],
            },
            "properties": {
                "codigo_ibge": previsao.codigo_ibge,
                "municipio": previsao.municipio,
                "uf": item.uf,
                "tipo_desastre": previsao.cobrade_grupo,
                "nivel_risco": previsao.nivel_risco,
                "confianca": previsao.confianca,
                "probabilidades": previsao.probabilidades,
                "cor": previsao.cor,
                "mes": item.mes,
            },
        }
        for item, previsao in zip(entrada.itens, previsoes)
    ]

    resumo = {classe: 0 for classe in esquema.CLASSES_RISCO}
    for p in previsoes:
        resumo[p.nivel_risco] += 1

    return {
        "type": "FeatureCollection",
        "features": feicoes,
        "metadados": {
            "total": len(feicoes),
            "resumo": resumo,
            "legenda": esquema.CORES_RISCO,
            "modelo_treinado_em": _treinado_em(),
        },
    }
