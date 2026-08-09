"""
API FastAPI que serve o modelo treinado de risco de desastres naturais.

Como executar (a partir da raiz do projeto):
    uvicorn backend.app:app --reload

Depois acesse http://127.0.0.1:8000/docs para testar pelo navegador.

Tudo roda localmente: o modelo é lido do arquivo modelos/modelo.pkl e as
previsões são calculadas na própria máquina, sem nenhuma chamada externa.
"""

import json
import sys
from pathlib import Path

# Permite rodar mesmo se a raiz do projeto não estiver no PYTHONPATH.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.esquemas import InfoModelo, Observacao, Previsao, RespostaLote
from treinamento.esquema import (
    ARQUIVO_METADADOS,
    ARQUIVO_MODELO,
    DESCRICAO_CLASSES,
    NOMES_COLUNAS,
)
from treinamento.treinar_modelo import VERSAO_MODELO

COMANDO_TREINO = "python treinamento/treinar_modelo.py"

app = FastAPI(
    title="API Fecart 2026 — Risco de Desastres Naturais",
    description=(
        "Prevê o tipo de desastre natural mais provável a partir de condições "
        "climáticas e geográficas. O modelo é um Random Forest treinado "
        "localmente."
    ),
    version=VERSAO_MODELO,
)

# Libera o acesso a partir do front-end aberto em outra porta (ex.: Live Server).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Estado carregado uma única vez, quando o servidor sobe.
_modelo = None
_metadados: dict = {}
_erro_carregamento: str | None = None


def _carregar_modelo() -> None:
    """
    Carrega modelo e metadados, conferindo a integridade do que foi lido.

    Se algo estiver errado, o erro fica guardado e é devolvido pelos
    endpoints com uma mensagem clara, em vez de derrubar o servidor.
    """
    global _modelo, _metadados, _erro_carregamento

    if not ARQUIVO_MODELO.exists():
        _erro_carregamento = (
            f"Modelo não encontrado em '{ARQUIVO_MODELO.name}'. "
            f"Rode primeiro: {COMANDO_TREINO}"
        )
        return

    try:
        _modelo = joblib.load(ARQUIVO_MODELO)
    except Exception as erro:
        _erro_carregamento = (
            f"Falha ao ler o modelo: {erro}. "
            f"Gere o modelo novamente com: {COMANDO_TREINO}"
        )
        return

    if ARQUIVO_METADADOS.exists():
        with open(ARQUIVO_METADADOS, encoding="utf-8") as arquivo:
            _metadados = json.load(arquivo)

    # Um `git pull` pode trazer um esquema novo enquanto o modelo local ainda
    # é antigo. Recusar aqui evita previsões silenciosamente erradas.
    versao_salva = _metadados.get("versao_modelo")
    if versao_salva and versao_salva != VERSAO_MODELO:
        _modelo = None
        _erro_carregamento = (
            f"O modelo salvo é da versão {versao_salva}, mas o código espera "
            f"a versão {VERSAO_MODELO}. Retreine com: {COMANDO_TREINO}"
        )
        return

    colunas_salvas = _metadados.get("colunas_entrada")
    if colunas_salvas and list(colunas_salvas) != list(NOMES_COLUNAS):
        _modelo = None
        _erro_carregamento = (
            "As colunas do modelo salvo não batem com o esquema atual. "
            f"Retreine com: {COMANDO_TREINO}"
        )
        return

    _erro_carregamento = None


_carregar_modelo()


def _exigir_modelo():
    """Devolve o modelo pronto para uso ou um erro HTTP explicativo."""
    if _modelo is None:
        raise HTTPException(status_code=503, detail=_erro_carregamento)
    return _modelo


def _nivel_risco(probabilidade: float) -> str:
    if probabilidade < 0.25:
        return "baixo"
    if probabilidade < 0.50:
        return "moderado"
    if probabilidade < 0.75:
        return "alto"
    return "muito_alto"


def _prever(observacoes: list[Observacao]) -> list[Previsao]:
    """Roda o modelo em uma ou mais observações."""
    modelo = _exigir_modelo()

    # A ordem das colunas segue o esquema, igual ao treino.
    entrada = pd.DataFrame(
        [obs.model_dump() for obs in observacoes], columns=list(NOMES_COLUNAS)
    )

    probabilidades = modelo.predict_proba(entrada)
    classes = list(modelo.classes_)

    resultados: list[Previsao] = []
    for linha in probabilidades:
        por_classe = {
            str(classe): round(float(p), 4) for classe, p in zip(classes, linha)
        }
        classe_prevista = max(por_classe, key=por_classe.get)
        risco = round(1.0 - por_classe.get("nenhum", 0.0), 4)

        resultados.append(
            Previsao(
                tipo_desastre_previsto=classe_prevista,
                descricao=DESCRICAO_CLASSES.get(classe_prevista, classe_prevista),
                confianca=por_classe[classe_prevista],
                probabilidade_algum_desastre=risco,
                nivel_risco=_nivel_risco(risco),
                probabilidades=dict(
                    sorted(por_classe.items(), key=lambda item: item[1], reverse=True)
                ),
            )
        )

    return resultados


@app.get("/", tags=["status"])
def raiz():
    """Informações básicas da API."""
    return {
        "projeto": "Fecart 2026 — Risco de Desastres Naturais",
        "modelo_carregado": _modelo is not None,
        "erro": _erro_carregamento,
        "documentacao": "/docs",
    }


@app.get("/saude", tags=["status"])
def saude():
    """Verificação rápida de que o servidor e o modelo estão de pé."""
    if _modelo is None:
        raise HTTPException(status_code=503, detail=_erro_carregamento)
    return {"status": "ok"}


@app.get("/modelo/info", response_model=InfoModelo, tags=["modelo"])
def info_modelo() -> InfoModelo:
    """Metadados do modelo: quando foi treinado, com quais dados e seu desempenho."""
    if _modelo is None:
        return InfoModelo(modelo_carregado=False, aviso=_erro_carregamento)

    aviso = None
    if _metadados.get("origem_dados") == "sintetico":
        aviso = (
            "Modelo treinado com dados SINTÉTICOS (fictícios). As previsões "
            "servem para demonstrar o funcionamento do sistema e não devem ser "
            "usadas para decisões reais."
        )

    return InfoModelo(
        modelo_carregado=True,
        versao_modelo=_metadados.get("versao_modelo"),
        treinado_em=_metadados.get("treinado_em"),
        origem_dados=_metadados.get("origem_dados"),
        aviso=aviso,
        classes=_metadados.get("classes", []),
        metricas=_metadados.get("metricas", {}),
        importancia_variaveis=_metadados.get("importancia_variaveis", {}),
        ambiente_treino=_metadados.get("ambiente", {}),
    )


@app.get("/opcoes", tags=["modelo"])
def opcoes():
    """
    Valores aceitos em cada campo.

    Útil para o front-end montar os menus suspensos sem repetir listas fixas.
    """
    from treinamento.esquema import COLUNAS

    return {
        "campos": [
            {
                "nome": c.nome,
                "tipo": c.tipo,
                "descricao": c.descricao,
                "unidade": c.unidade,
                "minimo": c.minimo,
                "maximo": c.maximo,
                "categorias": list(c.categorias),
                "exemplo": c.exemplo,
            }
            for c in COLUNAS
        ],
        "classes": DESCRICAO_CLASSES,
    }


@app.post("/prever", response_model=Previsao, tags=["previsao"])
def prever(observacao: Observacao) -> Previsao:
    """Prevê o tipo de desastre mais provável para uma observação."""
    return _prever([observacao])[0]


@app.post("/prever-lote", response_model=RespostaLote, tags=["previsao"])
def prever_lote(observacoes: list[Observacao]) -> RespostaLote:
    """Prevê várias observações de uma vez (por exemplo, todos os meses do ano)."""
    if not observacoes:
        raise HTTPException(status_code=400, detail="Envie ao menos uma observação.")
    if len(observacoes) > 1000:
        raise HTTPException(
            status_code=400, detail="Envie no máximo 1000 observações por chamada."
        )

    previsoes = _prever(observacoes)
    return RespostaLote(total=len(previsoes), previsoes=previsoes)
