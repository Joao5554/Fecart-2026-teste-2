"""
Backend FastAPI para servir o modelo treinado.

Como executar (a partir da raiz do projeto):
    uvicorn backend.app:app --reload

Depois acesse http://127.0.0.1:8000/docs para testar a API pelo navegador.
"""

from pathlib import Path

import joblib
from fastapi import FastAPI
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_MODELO = RAIZ / "modelo.pkl"

app = FastAPI(title="API Fecart 2026")

# O modelo é carregado uma única vez, quando o servidor sobe.
# Se o arquivo ainda não existe, rode antes: python treinamento/treinar_modelo.py
modelo = joblib.load(ARQUIVO_MODELO) if ARQUIVO_MODELO.exists() else None


class DadosEntrada(BaseModel):
    # TODO: trocar pelos campos reais que o modelo usa como entrada
    # Exemplo:
    # idade: float
    # renda: float
    valores: list[float]


@app.get("/")
def raiz():
    return {"status": "ok", "modelo_carregado": modelo is not None}


@app.post("/prever")
def prever(entrada: DadosEntrada):
    if modelo is None:
        return {"erro": "Modelo não encontrado. Rode: python treinamento/treinar_modelo.py"}

    previsao = modelo.predict([entrada.valores])
    return {"previsao": previsao.tolist()[0]}
