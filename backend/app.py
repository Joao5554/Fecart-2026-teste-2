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
    GET  /mapa/capitais        as 27 capitais, para marcar no mapa
"""

import json
import math
import sys
import unicodedata
from pathlib import Path

import joblib
import numpy as np
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
        # Validação por janela expansiva: o modelo é testado ano a ano, sempre
        # treinando só com o que veio antes. Traz média, desvio e o pior ano.
        "validacao_temporal": metadados.get("validacao_temporal"),
        "escolha_hiperparametros": metadados.get("escolha_hiperparametros"),
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


# --------------------------------------------------------------------------
# Histórico por ano
# --------------------------------------------------------------------------
# Estes dois endpoints não usam o modelo: respondem só o que o Atlas registrou.
# É uma diferença que vale manter visível, porque muda como o número deve ser
# lido. O mapa de risco mostra uma estimativa, que pode errar; o mapa do ano
# mostra o que de fato aconteceu, e não erra — no máximo está incompleto,
# quando o município não informou a ocorrência à Defesa Civil.

# Faixas de contagem para colorir o mapa do ano. Cinco classes, porque a
# distribuição é muito torta: a maioria dos municípios tem 1 ou 2 ocorrências
# no ano e uns poucos passam de 10. Uma escala linear jogaria quase todo mundo
# na mesma cor e esconderia justamente a variação que interessa.
FAIXAS_OCORRENCIAS = [
    (1, 1, "#F6C445", "1 ocorrência"),
    (2, 2, "#F08A3C", "2 ocorrências"),
    (3, 4, "#E05A34", "3 a 4"),
    (5, 9, "#B62D25", "5 a 9"),
    (10, None, "#6E1013", "10 ou mais"),
]


def _cor_por_ocorrencias(quantidade: int) -> str:
    for minimo, maximo, cor, _ in FAIXAS_OCORRENCIAS:
        if quantidade >= minimo and (maximo is None or quantidade <= maximo):
            return cor
    return FAIXAS_OCORRENCIAS[-1][2]


@app.get("/historico/anos", tags=["historico"])
def anos_com_registro():
    """
    Quais anos existem no Atlas, e quanto cada um registrou.

    A interface monta o seletor de ano a partir daqui, em vez de trazer
    1991–2025 escrito no código: quando a base for atualizada com 2026, o
    seletor cresce sozinho.
    """
    registros = _exigir_ocorrencias()

    por_ano = (
        registros.groupby("ano")
        .agg(ocorrencias=("mes", "size"),
             municipios=("codigo_ibge", "nunique"),
             mortos=("mortos", "sum"))
        .reset_index()
        .sort_values("ano")
    )

    return {
        "primeiro_ano": int(registros["ano"].min()),
        "ultimo_ano": int(registros["ano"].max()),
        "anos": [
            {"ano": int(linha.ano), "ocorrencias": int(linha.ocorrencias),
             "municipios": int(linha.municipios), "mortos": int(linha.mortos)}
            for linha in por_ano.itertuples()
        ],
    }


@app.get("/historico/ano/{ano}", tags=["historico"])
def historico_do_ano(ano: int, grupo_desastre: str | None = None):
    """
    Tudo que o Atlas registrou num ano, pronto para desenhar no mapa.

    Cada município vem com a cor da faixa em que caiu, seguindo o mesmo
    contrato do `/mapa/brasil`: quem desenha o mapa não precisa saber de
    escala de cor nenhuma, só pintar o que a API mandou.
    """
    registros = _exigir_ocorrencias()

    do_ano = registros[registros["ano"] == ano]
    if grupo_desastre:
        do_ano = do_ano[do_ano["grupo_desastre"] == grupo_desastre]

    if do_ano.empty:
        detalhe = f"O Atlas não tem ocorrências registradas em {ano}"
        if grupo_desastre:
            detalhe += f" para '{grupo_desastre}'"
        disponivel = f"{registros['ano'].min()}–{registros['ano'].max()}"
        raise HTTPException(
            status_code=404, detail=f"{detalhe}. Período disponível: {disponivel}."
        )

    por_municipio = (
        do_ano.groupby("codigo_ibge")
        .agg(municipio=("municipio", "last"), uf=("uf", "last"),
             ocorrencias=("mes", "size"), mortos=("mortos", "sum"),
             afetados=("afetados", "sum"), reconhecidos=("reconhecido", "sum"))
        .reset_index()
        .sort_values(["ocorrencias", "afetados"], ascending=False)
    )

    # Quais tipos atingiram cada município, para a dica do mapa dizer algo
    # mais útil que "3 ocorrências".
    tipos_por_municipio = (
        do_ano.groupby(["codigo_ibge", "grupo_desastre"]).size()
        .reset_index(name="n").sort_values("n", ascending=False)
        .groupby("codigo_ibge")["grupo_desastre"].apply(list).to_dict()
    )

    municipios = [
        {
            "codigo_ibge": int(linha.codigo_ibge),
            "municipio": linha.municipio,
            "uf": linha.uf,
            "ocorrencias": int(linha.ocorrencias),
            "mortos": int(linha.mortos),
            "afetados": int(linha.afetados),
            "reconhecidos": int(linha.reconhecidos),
            "tipos": tipos_por_municipio.get(linha.codigo_ibge, []),
            "cor": _cor_por_ocorrencias(int(linha.ocorrencias)),
        }
        for linha in por_municipio.itertuples()
    ]

    por_tipo = (
        do_ano.groupby("grupo_desastre")
        .agg(ocorrencias=("mes", "size"), municipios=("codigo_ibge", "nunique"),
             mortos=("mortos", "sum"), afetados=("afetados", "sum"))
        .reset_index().sort_values("ocorrencias", ascending=False)
    )

    por_uf = (
        do_ano.groupby("uf")
        .agg(ocorrencias=("mes", "size"), municipios=("codigo_ibge", "nunique"))
        .reset_index().sort_values("ocorrencias", ascending=False)
    )

    contagem_mensal = do_ano.groupby("mes").size()
    por_mes = [int(contagem_mensal.get(m, 0)) for m in range(1, 13)]

    return {
        "ano": ano,
        "grupo_desastre": grupo_desastre,
        "total_ocorrencias": int(len(do_ano)),
        "municipios_atingidos": int(do_ano["codigo_ibge"].nunique()),
        "ufs_atingidas": int(do_ano["uf"].nunique()),
        "mortos": int(do_ano["mortos"].sum()),
        "afetados": int(do_ano["afetados"].sum()),
        "reconhecidos": int(do_ano["reconhecido"].sum()),
        "por_tipo": [
            {"grupo_desastre": linha.grupo_desastre,
             "ocorrencias": int(linha.ocorrencias),
             "municipios": int(linha.municipios),
             "mortos": int(linha.mortos), "afetados": int(linha.afetados)}
            for linha in por_tipo.itertuples()
        ],
        "por_uf": [
            {"uf": linha.uf, "ocorrencias": int(linha.ocorrencias),
             "municipios": int(linha.municipios)}
            for linha in por_uf.itertuples()
        ],
        "por_mes": por_mes,
        "legenda": [
            {"cor": cor, "rotulo": rotulo, "de": minimo, "ate": maximo}
            for minimo, maximo, cor, rotulo in FAIXAS_OCORRENCIAS
        ],
        "municipios": municipios,
    }


# --------------------------------------------------------------------------
# Chuva medida (camada opcional dos mapas)
# --------------------------------------------------------------------------
# Serve os PONTOS de medição, não valores por município — e a distinção é o
# ponto principal deste endpoint.
#
# O `clima_mensal.csv`, que alimenta o modelo, tem uma linha por município,
# mas em 92% delas a chuva vem de uma estação de outro município: só 8% do
# país tem estação própria. Isso é aceitável como variável de entrada (e a
# coluna `fonte_clima` registra a qualidade de cada linha), mas desenhar um
# mapa com esses valores afirmaria uma medição que nunca foi feita ali.
#
# Aqui vão as 662 estações reais, com as coordenadas onde mediram. Quem
# desenha interpola entre elas e mostra os pontos por cima, para o leitor ver
# de onde a mancha veio.

ARQUIVO_ESTACOES = RAIZ / "dados" / "clima_estacoes.csv"

chuva_estacoes: pd.DataFrame | None = None

# Faixas em milímetros. Duas escalas porque as grandezas não se comparam: um
# mês de 200 mm é chuvoso, um ano de 200 mm é semiárido.
ESCALA_CHUVA_MES = [
    (0, 5, "#EAF4FB", "até 5 mm"),
    (5, 25, "#BBDCF0", "5 a 25"),
    (25, 60, "#7FC0E4", "25 a 60"),
    (60, 120, "#3F93CE", "60 a 120"),
    (120, 200, "#2E7D5B", "120 a 200"),
    (200, 300, "#94C13D", "200 a 300"),
    (300, 450, "#EFB61C", "300 a 450"),
    (450, None, "#D2451E", "mais de 450"),
]

ESCALA_CHUVA_ANO = [
    (0, 250, "#EAF4FB", "até 250 mm"),
    (250, 500, "#BBDCF0", "250 a 500"),
    (500, 800, "#7FC0E4", "500 a 800"),
    (800, 1200, "#3F93CE", "800 a 1.200"),
    (1200, 1600, "#2E7D5B", "1.200 a 1.600"),
    (1600, 2000, "#94C13D", "1.600 a 2.000"),
    (2000, 2600, "#EFB61C", "2.000 a 2.600"),
    (2600, None, "#D2451E", "mais de 2.600"),
]

MESES_POR_EXTENSO = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def carregar_chuva() -> bool:
    """Carrega a medição de chuva de cada estação do INMET."""
    global chuva_estacoes

    if not ARQUIVO_ESTACOES.exists():
        chuva_estacoes = None
        return False

    chuva_estacoes = pd.read_csv(ARQUIVO_ESTACOES)
    return True


carregar_chuva()


@app.get("/clima/chuva", tags=["clima"])
def chuva_medida(ano: int | None = None, mes: int | None = None):
    """
    Chuva medida em cada estação do INMET, num mês ou num ano inteiro.

    Sem `mes`, devolve o acumulado do ano — que é o que o mapa por ano pede.

    Sem `ano`, usa o ano mais recente com medição. É o que o mapa de risco
    precisa: ele prevê um ano que ainda não aconteceu, e chuva de 2026 não
    existe. A resposta sempre diz de que período é o número, no campo
    `periodo`, para a tela nunca mostrar uma medição sem data.
    """
    if chuva_estacoes is None:
        raise HTTPException(
            status_code=503,
            detail=("Dados de chuva não preparados (dados/clima_estacoes.csv).\n"
                    "Rode: python dados/preparar_clima.py"),
        )

    if mes is not None and not 1 <= mes <= 12:
        raise HTTPException(status_code=422, detail="mês precisa estar entre 1 e 12")

    primeiro = int(chuva_estacoes["ano"].min())
    ultimo = int(chuva_estacoes["ano"].max())
    if ano is None:
        ano = ultimo

    recorte = chuva_estacoes[chuva_estacoes["ano"] == ano]
    if mes is not None:
        recorte = recorte[recorte["mes"] == mes]

    if recorte.empty:
        quando = f"{MESES_POR_EXTENSO[mes - 1]} de {ano}" if mes else str(ano)
        raise HTTPException(
            status_code=404,
            detail=(f"O INMET não tem medição de chuva para {quando}. "
                    f"As estações automáticas cobrem {primeiro}–{ultimo} — "
                    f"antes disso a rede ainda não existia."),
        )

    # Uma estação pode ter mais de uma linha no ano (uma por mês). No modo
    # anual as chuvas somam; no mensal já vem uma linha por estação.
    por_estacao = (
        recorte.groupby(["estacao", "uf"], as_index=False)
        .agg(latitude=("latitude", "first"), longitude=("longitude", "first"),
             chuva_mm=("chuva_total_mm", "sum"),
             chuva_max_dia_mm=("chuva_max_dia_mm", "max"),
             dias_com_chuva=("dias_com_chuva", "sum"),
             meses_medidos=("mes", "nunique"))
    )

    escala = ESCALA_CHUVA_MES if mes else ESCALA_CHUVA_ANO

    return {
        "ano": ano,
        "mes": mes,
        "periodo": (f"{MESES_POR_EXTENSO[mes - 1]} de {ano}" if mes else str(ano)),
        "unidade": "mm",
        "cobertura": {"primeiro_ano": primeiro, "ultimo_ano": ultimo},
        "total_estacoes": int(len(por_estacao)),
        "chuva_media_mm": round(float(por_estacao["chuva_mm"].mean()), 1),
        "chuva_maxima_mm": round(float(por_estacao["chuva_mm"].max()), 1),
        "escala": [
            {"de": de, "ate": ate, "cor": cor, "rotulo": rotulo}
            for de, ate, cor, rotulo in escala
        ],
        "estacoes": [
            {
                "estacao": linha.estacao,
                "uf": linha.uf,
                "lat": float(linha.latitude),
                "lon": float(linha.longitude),
                "chuva_mm": round(float(linha.chuva_mm), 1),
                "chuva_max_dia_mm": round(float(linha.chuva_max_dia_mm), 1),
                "dias_com_chuva": int(linha.dias_com_chuva),
                "meses_medidos": int(linha.meses_medidos),
            }
            for linha in por_estacao.itertuples()
        ],
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
        # NaN não existe em JSON: variável sem medição vira null, que o
        # JavaScript entende. Deixar NaN produziria um JSON que parsers
        # estritos recusam.
        "historico_usado": {
            chave: (None if isinstance(valor, float) and math.isnan(valor) else valor)
            for chave, valor in features.items() if chave != "mes"
        },
        "modelo_treinado_em": _treinado_em(),
    }


ARQUIVO_MALHA = RAIZ / "dados" / "malha_municipios.json"

# O mapa do país inteiro custa milhares de previsões. Como o resultado só muda
# quando muda (tipo, mês, ano), guardá-lo em memória evita refazer a conta a
# cada clique na interface.
_cache_mapa: dict[tuple, dict] = {}


@app.get("/mapa/malha", tags=["mapa"])
def malha_municipios():
    """
    Fronteiras dos municípios brasileiros, em GeoJSON.

    Vem do IBGE em qualidade reduzida (~3 MB para os 5.570 municípios), o
    suficiente para desenhar o país inteiro sem depender de nenhum serviço
    de mapas externo.
    """
    if not ARQUIVO_MALHA.exists():
        raise HTTPException(
            status_code=404,
            detail=("Malha municipal não encontrada.\n"
                    "Rode: python dados/baixar_malha.py"),
        )

    from fastapi.responses import FileResponse

    return FileResponse(ARQUIVO_MALHA, media_type="application/geo+json")


# As capitais são calculadas uma vez e ficam em memória: a malha tem 3 MB e
# abrir o arquivo a cada clique no interruptor não se justifica para 27 pontos.
_cache_capitais: list[dict] | None = None


def _centro_do_poligono(anel: list) -> tuple[float, float]:
    """
    Centro geométrico de um anel de coordenadas (fórmula do centroide de
    polígono, não a média dos vértices).

    A diferença aparece em município de contorno recortado, onde um trecho de
    litoral concentra dezenas de vértices: a média puxaria o ponto para lá, e
    o marcador da capital sairia de cima da mancha urbana.
    """
    area = cx = cy = 0.0
    for i in range(len(anel) - 1):
        x1, y1 = anel[i][0], anel[i][1]
        x2, y2 = anel[i + 1][0], anel[i + 1][1]
        cruzado = x1 * y2 - x2 * y1
        area += cruzado
        cx += (x1 + x2) * cruzado
        cy += (y1 + y2) * cruzado

    if area == 0:  # anel degenerado: cai para a média simples
        return (sum(c[0] for c in anel) / len(anel),
                sum(c[1] for c in anel) / len(anel))

    return cx / (3 * area), cy / (3 * area)


@app.get("/mapa/capitais", tags=["mapa"])
def capitais_no_mapa():
    """
    As 27 capitais estaduais, com o ponto onde marcá-las no mapa.

    O mapa pinta 5.570 municípios e não escreve nenhum nome. Sem referência
    nenhuma, quem olha vê manchas de cor e não sabe onde está olhando — as
    capitais dão o ponto de apoio que o olho procura primeiro.

    A coordenada é o centroide do maior polígono do município, calculado a
    partir da mesma malha que desenha o mapa: assim o marcador cai sempre
    dentro do contorno que ele nomeia.
    """
    global _cache_capitais

    if _cache_capitais is not None:
        return {"total": len(_cache_capitais), "capitais": _cache_capitais}

    if not ARQUIVO_MALHA.exists():
        raise HTTPException(
            status_code=404,
            detail=("Malha municipal não encontrada.\n"
                    "Rode: python dados/baixar_malha.py"),
        )

    with open(ARQUIVO_MALHA, encoding="utf-8") as arquivo:
        malha = json.load(arquivo)

    por_codigo = {f["properties"]["codigo_ibge"]: f for f in malha["features"]}

    capitais = []
    for uf, (codigo, nome) in esquema.CAPITAIS.items():
        feicao = por_codigo.get(codigo)
        if feicao is None:
            continue

        geometria = feicao["geometry"]
        poligonos = ([geometria["coordinates"]]
                     if geometria["type"] == "Polygon"
                     else geometria["coordinates"])
        # Ilha isolada não representa a cidade: entre os polígonos do
        # município vale o maior, que é onde a capital de fato está.
        maior = max((p[0] for p in poligonos), key=len)
        lon, lat = _centro_do_poligono(maior)

        capitais.append({
            "uf": uf,
            "codigo_ibge": codigo,
            "nome": nome,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
        })

    _cache_capitais = capitais
    return {"total": len(capitais), "capitais": capitais}


@app.get("/mapa/brasil", tags=["mapa"])
def mapa_brasil(grupo_desastre: str, mes: int, ano: int = 2026):
    """
    Nível de risco de todos os municípios do país, de uma vez.

    É o que pinta o mapa. Só entram municípios com histórico daquele tipo de
    desastre no Atlas — sobre os demais o modelo não tem o que dizer, e um
    mapa que os pintasse de verde estaria afirmando algo que não sabe.
    """
    registros = _exigir_ocorrencias()
    modelo_ativo = exigir_modelo()

    if not 1 <= mes <= 12:
        raise HTTPException(status_code=422, detail="mês precisa estar entre 1 e 12")

    chave = (grupo_desastre, mes, ano)
    if chave in _cache_mapa:
        return _cache_mapa[chave]

    do_tipo = registros[registros["grupo_desastre"] == grupo_desastre]
    if do_tipo.empty:
        raise HTTPException(
            status_code=404,
            detail=(f"Nenhum município tem histórico de '{grupo_desastre}'. "
                    f"Tipos disponíveis: {', '.join(esquema.GRUPOS_COBRADE)}"),
        )

    municipios = do_tipo.drop_duplicates("codigo_ibge")[
        ["codigo_ibge", "municipio", "uf", "regiao"]
    ]

    # Uma única chamada calcula as features de todos os municípios: a versão
    # por município seria milhares de chamadas e levaria minutos.
    historico = atlas.agregar_por_mes(registros)
    alvos = pd.DataFrame({
        "codigo_ibge": municipios["codigo_ibge"].to_numpy(),
        "grupo_desastre": grupo_desastre,
        "indice_mes": atlas._indice_mes(ano, mes),
    })

    entrada = atlas.calcular_features(historico, alvos)
    entrada["prejuizo_historico_log"] = np.log1p(entrada["prejuizo_historico"])
    entrada["mes"] = mes
    entrada = entrada.merge(municipios, on="codigo_ibge", how="left")

    X = caracteristicas.preparar_para_previsao(entrada)
    probabilidades = modelo_ativo.predict_proba(X)
    classes = list(modelo_ativo.classes_)
    indice_alto = classes.index("alto") if "alto" in classes else None

    resultado = []
    for posicao, linha in enumerate(entrada.itertuples()):
        por_classe = {
            c: round(float(probabilidades[posicao][i]), 4)
            for i, c in enumerate(classes)
        }
        nivel = max(por_classe, key=por_classe.get)
        resultado.append({
            "codigo_ibge": int(linha.codigo_ibge),
            "municipio": linha.municipio,
            "uf": linha.uf,
            "nivel_risco": nivel,
            "probabilidade_alto": (
                round(float(probabilidades[posicao][indice_alto]), 4)
                if indice_alto is not None else 0.0
            ),
            "cor": esquema.CORES_RISCO[nivel],
        })

    resumo = {classe: 0 for classe in esquema.CLASSES_RISCO}
    for item in resultado:
        resumo[item["nivel_risco"]] += 1

    resposta = {
        "grupo_desastre": grupo_desastre,
        "mes": mes,
        "ano": ano,
        "total": len(resultado),
        "resumo": resumo,
        "legenda": esquema.CORES_RISCO,
        "municipios": resultado,
        "modelo_treinado_em": _treinado_em(),
    }

    _cache_mapa[chave] = resposta
    return resposta


@app.get("/mapa/municipio/{codigo_ibge}", tags=["mapa"])
def mapa_do_municipio(codigo_ibge: int, grupo_desastre: str, mes: int,
                      ano: int = 2026):
    """
    O município e sua vizinhança, para o mapa ampliado da cidade.

    Devolve o município consultado e os que ficam na mesma região imediata do
    IBGE, cada um com seu nível de risco. É a leitura útil na escala local:
    um desastre raramente respeita divisa municipal, e ver o entorno mostra se
    a cidade é um ponto isolado ou parte de uma área inteira sob pressão.

    **Não há divisão de bairros aqui.** O Atlas registra quais setores
    censitários foram atingidos, mas o IBGE não publica a geometria desses
    setores por API — desenhá-los exigiria inventar os limites. Em vez disso,
    a resposta traz quantos setores distintos já foram afetados, que é um dado
    real.
    """
    registros = _exigir_ocorrencias()

    do_municipio = registros[registros["codigo_ibge"] == codigo_ibge]
    if do_municipio.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Município {codigo_ibge} não tem histórico no Atlas.",
        )

    vizinhos = _vizinhos_do_municipio(codigo_ibge)
    mapa_pais = mapa_brasil(grupo_desastre=grupo_desastre, mes=mes, ano=ano)
    por_codigo = {m["codigo_ibge"]: m for m in mapa_pais["municipios"]}

    selecionados = [
        {**por_codigo[c], "e_o_consultado": c == codigo_ibge}
        for c in vizinhos if c in por_codigo
    ]

    return {
        "codigo_ibge": codigo_ibge,
        "municipio": do_municipio["municipio"].iloc[-1],
        "uf": do_municipio["uf"].iloc[-1],
        "grupo_desastre": grupo_desastre,
        "mes": mes,
        "codigos_da_vizinhanca": vizinhos,
        "municipios": selecionados,
        "setores_afetados": _setores_do_municipio(do_municipio, grupo_desastre),
        "legenda": esquema.CORES_RISCO,
    }


def _vizinhos_do_municipio(codigo_ibge: int) -> list[int]:
    """
    Códigos do município e dos que compartilham sua região imediata.

    Sem a lista do IBGE disponível, cai para os municípios da mesma UF que
    têm histórico — menos preciso, mas ainda desenha um mapa útil.
    """
    try:
        from src import regioes

        municipios = regioes.carregar_municipios()
        linha = municipios[municipios["codigo_ibge"] == codigo_ibge]
        if not linha.empty and pd.notna(linha["regiao_imediata"].iloc[0]):
            regiao = linha["regiao_imediata"].iloc[0]
            vizinhos = municipios[municipios["regiao_imediata"] == regiao]
            return sorted(int(c) for c in vizinhos["codigo_ibge"])
    except Exception:
        pass

    registros = _exigir_ocorrencias()
    uf = registros[registros["codigo_ibge"] == codigo_ibge]["uf"].iloc[-1]
    return sorted(
        int(c) for c in registros[registros["uf"] == uf]["codigo_ibge"].unique()
    )


def _setores_do_municipio(do_municipio: pd.DataFrame, grupo: str) -> dict:
    """Quantas partes distintas da cidade já foram atingidas, segundo o Atlas."""
    if "setores" not in do_municipio.columns:
        return {"disponivel": False}

    do_tipo = do_municipio[do_municipio["grupo_desastre"] == grupo]
    listas = do_tipo["setores"].fillna("").astype(str)

    distintos = set()
    com_registro = 0
    for lista in listas:
        partes = {p.strip() for p in lista.split(",") if p.strip()}
        if partes:
            com_registro += 1
            distintos |= partes

    return {
        "disponivel": bool(distintos),
        "setores_distintos": len(distintos),
        "ocorrencias_com_setor": com_registro,
        "ocorrencias_do_tipo": int(len(do_tipo)),
        "observacao": (
            "O Atlas registra quais setores censitários foram atingidos, mas o "
            "IBGE não publica a geometria deles por API — por isso o número "
            "aparece sem o desenho."
        ),
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
