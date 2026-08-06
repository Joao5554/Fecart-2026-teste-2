"""
Testes da API.

Usam o TestClient do FastAPI: fazem requisições de verdade contra a aplicação,
sem precisar subir o uvicorn.
"""

import math
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_MODELO = RAIZ / "modelo" / "modelo.pkl"

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import app  # noqa: E402
from src import esquema  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

# Os endpoints de previsão só funcionam com um modelo treinado no disco.
precisa_de_modelo = pytest.mark.skipif(
    not ARQUIVO_MODELO.exists(),
    reason="modelo não treinado — rode: python treinamento/treinar_modelo.py",
)


def montar_entrada(linha: dict) -> dict:
    """Converte uma linha do dataset no corpo esperado pelo POST /prever."""
    campos = (
        ["codigo_ibge", "municipio", "mes"]
        + esquema.COLUNAS_CATEGORICAS
        + esquema.COLUNAS_NUMERICAS
    )
    entrada = {}
    for campo in campos:
        valor = linha[campo]
        # JSON não tem NaN. Campos opcionais viram null; o modelo os imputa.
        if isinstance(valor, float) and math.isnan(valor):
            valor = None
        entrada[campo] = valor
    return entrada


# --------------------------------------------------------------------------
# Endpoints informativos
# --------------------------------------------------------------------------


def test_raiz_responde_o_estado():
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["niveis_de_risco"] == esquema.CLASSES_RISCO
    assert "DESLIZAMENTO" in corpo["tipos_de_desastre"]


def test_esquema_lista_todos_os_campos():
    resposta = cliente.get("/esquema")

    assert resposta.status_code == 200
    nomes = {c["nome"] for c in resposta.json()["campos"]}
    for esperado in esquema.COLUNAS_NUMERICAS + esquema.COLUNAS_CATEGORICAS:
        assert esperado in nomes


@precisa_de_modelo
def test_info_do_modelo_traz_metricas():
    resposta = cliente.get("/modelo/info")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "acuracia_balanceada" in corpo["metricas"]
    assert corpo["treinado_em"]


# --------------------------------------------------------------------------
# Previsão
# --------------------------------------------------------------------------


@precisa_de_modelo
def test_prever_devolve_nivel_e_probabilidades(linha_exemplo):
    resposta = cliente.post("/prever", json=montar_entrada(linha_exemplo))

    assert resposta.status_code == 200, resposta.text
    previsao = resposta.json()["previsao"]

    assert previsao["nivel_risco"] in esquema.CLASSES_RISCO
    assert set(previsao["probabilidades"]) == set(esquema.CLASSES_RISCO)
    assert abs(sum(previsao["probabilidades"].values()) - 1.0) < 0.01
    assert previsao["cor"] == esquema.CORES_RISCO[previsao["nivel_risco"]]


@precisa_de_modelo
def test_nivel_previsto_e_o_de_maior_probabilidade(linha_exemplo):
    resposta = cliente.post("/prever", json=montar_entrada(linha_exemplo))
    previsao = resposta.json()["previsao"]

    mais_provavel = max(
        previsao["probabilidades"], key=previsao["probabilidades"].get
    )
    assert previsao["nivel_risco"] == mais_provavel
    assert previsao["confianca"] == previsao["probabilidades"][mais_provavel]


@precisa_de_modelo
def test_campos_opcionais_podem_vir_vazios(linha_exemplo):
    """Município sem sensor de solo nem estação fluviométrica."""
    entrada = montar_entrada(linha_exemplo)
    entrada["umidade_solo_percentual"] = None
    entrada["nivel_rio_m"] = None

    resposta = cliente.post("/prever", json=entrada)

    assert resposta.status_code == 200, resposta.text


@precisa_de_modelo
def test_lote_devolve_uma_previsao_por_item(dados_exemplo):
    itens = [montar_entrada(l) for l in dados_exemplo.head(25).to_dict("records")]
    resposta = cliente.post("/prever/lote", json={"itens": itens})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] == 25
    assert len(corpo["previsoes"]) == 25
    assert sum(corpo["resumo"].values()) == 25


@precisa_de_modelo
def test_lote_e_previsao_individual_concordam(linha_exemplo):
    """O caminho em lote não pode dar resultado diferente do individual."""
    entrada = montar_entrada(linha_exemplo)

    individual = cliente.post("/prever", json=entrada).json()["previsao"]
    lote = cliente.post("/prever/lote", json={"itens": [entrada]}).json()["previsoes"][0]

    assert individual["nivel_risco"] == lote["nivel_risco"]
    assert individual["probabilidades"] == lote["probabilidades"]


# --------------------------------------------------------------------------
# Mapa
# --------------------------------------------------------------------------


@precisa_de_modelo
def test_mapa_devolve_geojson_valido(dados_exemplo):
    itens = [montar_entrada(l) for l in dados_exemplo.head(10).to_dict("records")]
    resposta = cliente.post("/mapa/risco", json={"itens": itens})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()

    assert corpo["type"] == "FeatureCollection"
    assert len(corpo["features"]) == 10
    for feicao in corpo["features"]:
        assert feicao["type"] == "Feature"
        assert feicao["geometry"]["type"] == "Point"
        assert len(feicao["geometry"]["coordinates"]) == 2


@precisa_de_modelo
def test_mapa_usa_a_ordem_longitude_latitude(dados_exemplo):
    """GeoJSON é [longitude, latitude]. Invertido, o ponto cai no oceano."""
    itens = [montar_entrada(l) for l in dados_exemplo.head(5).to_dict("records")]
    resposta = cliente.post("/mapa/risco", json={"itens": itens})

    for item, feicao in zip(itens, resposta.json()["features"]):
        longitude, latitude = feicao["geometry"]["coordinates"]
        assert longitude == item["longitude"]
        assert latitude == item["latitude"]
        # Sanidade extra: todo município brasileiro tem longitude negativa.
        assert -74 <= longitude <= -34
        assert -34 <= latitude <= 6


@precisa_de_modelo
def test_mapa_traz_legenda_e_resumo(dados_exemplo):
    itens = [montar_entrada(l) for l in dados_exemplo.head(10).to_dict("records")]
    resposta = cliente.post("/mapa/risco", json={"itens": itens})
    meta = resposta.json()["metadados"]

    assert meta["total"] == 10
    assert sum(meta["resumo"].values()) == 10
    assert set(meta["legenda"]) == set(esquema.CLASSES_RISCO)


# --------------------------------------------------------------------------
# Validação de entrada
# --------------------------------------------------------------------------


def test_mes_invalido_e_rejeitado(linha_exemplo):
    entrada = montar_entrada(linha_exemplo)
    entrada["mes"] = 13

    assert cliente.post("/prever", json=entrada).status_code == 422


def test_chuva_negativa_e_rejeitada(linha_exemplo):
    entrada = montar_entrada(linha_exemplo)
    entrada["chuva_acumulada_mm"] = -10

    assert cliente.post("/prever", json=entrada).status_code == 422


def test_campo_faltando_e_rejeitado(linha_exemplo):
    entrada = montar_entrada(linha_exemplo)
    del entrada["declividade_media_graus"]

    resposta = cliente.post("/prever", json=entrada)
    assert resposta.status_code == 422
    assert "declividade_media_graus" in resposta.text


def test_lote_vazio_e_rejeitado():
    assert cliente.post("/prever/lote", json={"itens": []}).status_code == 422
