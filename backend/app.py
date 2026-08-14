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
import unicodedata
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.esquemas_api import (  # noqa: E402
    ConsultaMunicipio,
    EntradaLote,
    EntradaPrevisao,
    Previsao,
    RespostaLote,
    RespostaPrevisao,
)
from src import atlas, caracteristicas, esquema  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_MODELO = RAIZ / "modelo" / "modelo.pkl"
ARQUIVO_METADADOS = RAIZ / "modelo" / "metadados.json"
ARQUIVO_OCORRENCIAS = RAIZ / "dados" / "ocorrencias.csv"

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
problema_modelo: str | None = MENSAGEM_SEM_MODELO


def carregar_modelo() -> bool:
    """Carrega o modelo e os metadados do disco. Devolve True se conseguiu."""
    global modelo, metadados, problema_modelo

    if not ARQUIVO_MODELO.exists():
        modelo, metadados = None, {}
        problema_modelo = MENSAGEM_SEM_MODELO
        return False

    try:
        modelo = joblib.load(ARQUIVO_MODELO)
    except Exception as erro:
        modelo, metadados = None, {}
        problema_modelo = (
            f"O arquivo do modelo existe, mas não pôde ser lido ({erro}).\n"
            "Gere o modelo de novo com: python treinamento/treinar_modelo.py"
        )
        return False

    # utf-8-sig lê tanto o arquivo normal quanto um que tenha ganhado BOM ao
    # ser editado no Windows. Um metadados.json quebrado não pode derrubar a
    # API: o modelo em si continua utilizável, apenas sem as informações extras.
    metadados = {}
    if ARQUIVO_METADADOS.exists():
        try:
            metadados = json.loads(ARQUIVO_METADADOS.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as erro:
            print(f"[aviso] metadados.json ilegível ({erro}); seguindo sem eles.")

    # O modelo no disco pode ter sido treinado com um contrato de dados
    # diferente do que este código usa agora (por exemplo, depois de um
    # `git pull` que mudou src/esquema.py). Nesse caso as colunas não
    # significam mais a mesma coisa: melhor recusar do que prever errado.
    assinatura_salva = metadados.get("assinatura_esquema")
    assinatura_atual = esquema.assinatura()
    if assinatura_salva and assinatura_salva != assinatura_atual:
        modelo = None
        problema_modelo = (
            "O modelo salvo foi treinado com outro formato de dados "
            f"(assinatura {assinatura_salva}, o código atual espera "
            f"{assinatura_atual}).\n"
            "Retreine antes de usar: python treinamento/treinar_modelo.py"
        )
        return False

    problema_modelo = None
    return True


# Carrega uma única vez, quando o servidor sobe. Carregar a cada requisição
# gastaria segundos por chamada.
carregar_modelo()


# --------------------------------------------------------------------------
# Histórico dos municípios (para as consultas simplificadas)
# --------------------------------------------------------------------------

ocorrencias: pd.DataFrame | None = None
_municipios: pd.DataFrame | None = None


def _sem_acento(texto: str) -> str:
    """Remove acentos e baixa a caixa, para a busca por nome ser tolerante."""
    normalizado = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def carregar_ocorrencias() -> bool:
    """
    Carrega as ocorrências limpas do Atlas.

    São elas que permitem a interface perguntar só "município, tipo e mês":
    o histórico é calculado aqui, com a mesma função usada no treino.
    """
    global ocorrencias, _municipios

    if not ARQUIVO_OCORRENCIAS.exists():
        ocorrencias, _municipios = None, None
        return False

    ocorrencias = pd.read_csv(ARQUIVO_OCORRENCIAS)
    _municipios = (
        ocorrencias.sort_values("ano")
        .groupby("codigo_ibge")
        .agg(municipio=("municipio", "last"), uf=("uf", "last"),
             regiao=("regiao", "last"), ocorrencias=("ano", "size"))
        .reset_index()
        .sort_values(["uf", "municipio"])
    )
    # Coluna auxiliar sem acento: quem digita "Petropolis" precisa encontrar
    # "Petrópolis". Fica pronta aqui para a busca não recalcular a cada chamada.
    _municipios["_busca"] = _municipios["municipio"].map(_sem_acento)
    return True


carregar_ocorrencias()


def _exigir_ocorrencias() -> pd.DataFrame:
    if ocorrencias is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Histórico de ocorrências não encontrado (dados/ocorrencias.csv).\n"
                "Rode: python dados/preparar_dados.py"
            ),
        )
    return ocorrencias


def exigir_modelo():
    """Devolve o modelo ou responde 503 com instruções claras."""
    if modelo is None:
        raise HTTPException(status_code=503, detail=problema_modelo or MENSAGEM_SEM_MODELO)
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
            grupo_desastre=entrada.grupo_desastre,
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
        "mensagem": None if modelo else problema_modelo,
        "treinado_em": _treinado_em() if modelo else None,
        "origem_dados": metadados.get("origem_dados") if modelo else None,
        "aviso": metadados.get("aviso_dados") if modelo else None,
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
        # Procedência: com qual base este modelo foi treinado, e o aviso
        # correspondente quando os dados são inventados.
        "origem_dados": metadados.get("origem_dados"),
        "aviso": metadados.get("aviso_dados"),
        "hash_dados_sha256": metadados.get("hash_dados_sha256"),
        "versao_esquema": metadados.get("versao_esquema"),
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


@app.get("/modelo/odds-ratio", tags=["modelo"])
def odds_ratio_modelo(analise: str | None = None):
    """
    Razão de chances (odds ratio) de cada variável.

    Enquanto a importância do Random Forest diz *quanto* uma variável ajuda a
    prever, o odds ratio diz em que **direção** ela empurra o risco e quanto
    multiplica a chance: OR 2,0 dobra, 1,0 não altera, 0,5 corta pela metade.

    Vem de uma regressão logística ajustada sobre os mesmos dados, e cada
    valor traz intervalo de confiança de 95% e p-valor.
    """
    exigir_modelo()

    resultados = metadados.get("odds_ratio") or {}
    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=(
                "Este modelo foi treinado sem a análise de odds ratio.\n"
                "Rode de novo: python treinamento/treinar_modelo.py"
            ),
        )

    if analise:
        if analise not in resultados:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Análise '{analise}' não encontrada. "
                    f"Disponíveis: {', '.join(resultados)}"
                ),
            )
        return resultados[analise]

    return {
        "analises": list(resultados),
        "como_ler": {
            "maior_que_1": "aumenta a chance",
            "igual_a_1": "não altera a chance",
            "menor_que_1": "reduz a chance",
            "unidade": "variação por 1 desvio-padrão da variável",
            "significativo": "falso quando o intervalo de confiança inclui 1,0",
        },
        "resultados": resultados,
    }


@app.post("/modelo/recarregar", tags=["modelo"])
def recarregar():
    """Recarrega o .pkl do disco, útil depois de treinar de novo.

    Evita ter que derrubar e subir o servidor a cada retreino.
    """
    if carregar_modelo():
        return {
            "status": "modelo recarregado",
            "treinado_em": _treinado_em(),
            "origem_dados": metadados.get("origem_dados"),
            "aviso": metadados.get("aviso_dados"),
        }
    raise HTTPException(status_code=404, detail=problema_modelo or MENSAGEM_SEM_MODELO)


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


@app.get("/municipios", tags=["consulta"])
def listar_municipios(uf: str | None = None, busca: str | None = None,
                      limite: int = 500):
    """
    Municípios com histórico no Atlas — é o que alimenta a busca da interface.

    Filtra por UF e/ou por parte do nome.
    """
    _exigir_ocorrencias()
    tabela = _municipios

    if uf:
        tabela = tabela[tabela["uf"].str.upper() == uf.strip().upper()]
    if busca:
        tabela = tabela[tabela["_busca"].str.contains(
            _sem_acento(busca.strip()), regex=False, na=False
        )]

    return {
        "total": int(len(tabela)),
        "municipios": tabela.drop(columns=["_busca"]).head(limite).to_dict("records"),
    }


@app.get("/municipios/{codigo_ibge}/historico", tags=["consulta"])
def historico_municipio(codigo_ibge: int):
    """Resumo do que já aconteceu no município, por tipo de desastre."""
    registros = _exigir_ocorrencias()
    do_municipio = registros[registros["codigo_ibge"] == codigo_ibge]

    if do_municipio.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Município {codigo_ibge} não tem ocorrências no Atlas.",
        )

    por_tipo = (
        do_municipio.groupby("grupo_desastre")
        .agg(ocorrencias=("ano", "size"), mortos=("mortos", "sum"),
             afetados=("afetados", "sum"), ultimo_ano=("ano", "max"))
        .reset_index()
        .sort_values("ocorrencias", ascending=False)
    )

    return {
        "codigo_ibge": codigo_ibge,
        "municipio": do_municipio["municipio"].iloc[-1],
        "uf": do_municipio["uf"].iloc[-1],
        "regiao": do_municipio["regiao"].iloc[-1],
        "total_ocorrencias": int(len(do_municipio)),
        "periodo": {
            "primeiro_ano": int(do_municipio["ano"].min()),
            "ultimo_ano": int(do_municipio["ano"].max()),
        },
        "por_tipo": por_tipo.to_dict("records"),
    }


@app.post("/prever/municipio", tags=["consulta"])
def prever_municipio(consulta: ConsultaMunicipio):
    """
    Previsão a partir apenas de município, tipo de desastre e mês.

    As quinze variáveis históricas são calculadas aqui, a partir do Atlas,
    com a mesma função usada no treino. É o endpoint que a interface usa.
    """
    registros = _exigir_ocorrencias()
    modelo_ativo = exigir_modelo()

    do_municipio = registros[registros["codigo_ibge"] == consulta.codigo_ibge]
    if do_municipio.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Município {consulta.codigo_ibge} não tem histórico no Atlas.",
        )

    features = atlas.features_para_consulta(
        registros, consulta.codigo_ibge, consulta.grupo_desastre,
        consulta.ano, consulta.mes,
    )

    entrada = pd.DataFrame([{
        **features,
        "uf": do_municipio["uf"].iloc[-1],
        "regiao": do_municipio["regiao"].iloc[-1],
        "grupo_desastre": consulta.grupo_desastre,
    }])

    X = caracteristicas.preparar_para_previsao(entrada)
    probabilidades = modelo_ativo.predict_proba(X)[0]
    classes = list(modelo_ativo.classes_)

    por_classe = {
        c: round(float(dict(zip(classes, probabilidades)).get(c, 0.0)), 4)
        for c in esquema.CLASSES_RISCO
    }
    nivel = max(por_classe, key=por_classe.get)

    return {
        "codigo_ibge": consulta.codigo_ibge,
        "municipio": do_municipio["municipio"].iloc[-1],
        "uf": do_municipio["uf"].iloc[-1],
        "grupo_desastre": consulta.grupo_desastre,
        "ano": consulta.ano,
        "mes": consulta.mes,
        "nivel_risco": nivel,
        "confianca": por_classe[nivel],
        "probabilidades": por_classe,
        "cor": esquema.CORES_RISCO[nivel],
        # Devolvido para a interface poder explicar a previsão a quem consulta.
        "historico_usado": {
            k: v for k, v in features.items() if k != "mes"
        },
        "modelo_treinado_em": _treinado_em(),
    }


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
                "tipo_desastre": previsao.grupo_desastre,
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


# --------------------------------------------------------------------------
# Interface web
# --------------------------------------------------------------------------
# Servir o frontend pela própria API evita depender do Live Server e elimina
# problemas de CORS: tudo passa a sair da mesma origem.
# Fica por último para não capturar as rotas declaradas acima.

PASTA_FRONTEND = RAIZ / "frontend"

if PASTA_FRONTEND.exists():
    app.mount(
        "/app",
        StaticFiles(directory=PASTA_FRONTEND, html=True),
        name="frontend",
    )
