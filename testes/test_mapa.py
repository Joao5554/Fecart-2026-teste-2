"""
Testes do mapa de risco.

O risco silencioso aqui é o mapa desenhar bonito e mentir: polígono casado com
o município errado, ou município sem histórico pintado de verde como se fosse
seguro. Os testes cobrem essas duas coisas.
"""

import json

import pytest

from src import esquema

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend import app as modulo_app  # noqa: E402
from backend.app import app  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

precisa_de_dados = pytest.mark.skipif(
    modulo_app.ocorrencias is None or modulo_app.modelo is None,
    reason="rode: python dados/preparar_dados.py && python treinamento/treinar_modelo.py",
)
precisa_de_malha = pytest.mark.skipif(
    not modulo_app.ARQUIVO_MALHA.exists(),
    reason="rode: python dados/baixar_malha.py",
)


# --------------------------------------------------------------------------
# Malha
# --------------------------------------------------------------------------


@precisa_de_malha
def test_malha_e_geojson_valido():
    resposta = cliente.get("/mapa/malha")
    assert resposta.status_code == 200

    geo = resposta.json()
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) > 5_000, "o Brasil tem 5.570 municípios"


@precisa_de_malha
def test_cada_poligono_traz_o_codigo_ibge():
    """Sem o código, não há como casar o polígono com a previsão."""
    geo = cliente.get("/mapa/malha").json()

    for feicao in geo["features"][:50]:
        codigo = feicao["properties"]["codigo_ibge"]
        assert isinstance(codigo, int)
        assert 1_000_000 <= codigo <= 9_999_999


@precisa_de_malha
def test_codigos_da_malha_nao_se_repetem():
    geo = cliente.get("/mapa/malha").json()
    codigos = [f["properties"]["codigo_ibge"] for f in geo["features"]]
    assert len(codigos) == len(set(codigos))


@precisa_de_malha
def test_coordenadas_caem_dentro_do_brasil():
    """
    Latitude e longitude trocadas é o erro clássico de mapa — o país inteiro
    iria parar no oceano Índico.
    """
    geo = cliente.get("/mapa/malha").json()

    def pontos(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for parte in coords:
                yield from pontos(parte)

    for feicao in geo["features"][:100]:
        for lon, lat in pontos(feicao["geometry"]["coordinates"]):
            assert -75 <= lon <= -33, f"longitude fora do Brasil: {lon}"
            assert -35 <= lat <= 6, f"latitude fora do Brasil: {lat}"


# --------------------------------------------------------------------------
# Risco por município
# --------------------------------------------------------------------------


@precisa_de_dados
def test_mapa_do_brasil_responde():
    resposta = cliente.get("/mapa/brasil",
                           params={"grupo_desastre": "INUNDACAO", "mes": 2})
    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["total"] > 100
    assert sum(dados["resumo"].values()) == dados["total"]
    assert set(dados["legenda"]) == set(esquema.CLASSES_RISCO)


@precisa_de_dados
def test_cada_municipio_tem_nivel_e_cor_coerentes():
    dados = cliente.get("/mapa/brasil",
                        params={"grupo_desastre": "INUNDACAO", "mes": 2}).json()

    for item in dados["municipios"][:200]:
        assert item["nivel_risco"] in esquema.CLASSES_RISCO
        assert item["cor"] == esquema.CORES_RISCO[item["nivel_risco"]]
        assert 0.0 <= item["probabilidade_alto"] <= 1.0


@precisa_de_dados
def test_so_entram_municipios_com_historico_do_tipo():
    """
    Um mapa que pintasse de verde os municípios sem histórico estaria
    afirmando "aqui é seguro" sobre lugares que o modelo não conhece.
    """
    dados = cliente.get("/mapa/brasil",
                        params={"grupo_desastre": "DESLIZAMENTO", "mes": 2}).json()

    registros = modulo_app.ocorrencias
    com_historico = set(
        registros[registros["grupo_desastre"] == "DESLIZAMENTO"]["codigo_ibge"]
    )
    no_mapa = {m["codigo_ibge"] for m in dados["municipios"]}

    assert no_mapa <= com_historico, "entrou município sem histórico deste tipo"


@precisa_de_dados
@precisa_de_malha
def test_todo_municipio_do_mapa_tem_fronteira():
    """Sem fronteira o município simplesmente não apareceria no desenho."""
    dados = cliente.get("/mapa/brasil",
                        params={"grupo_desastre": "INUNDACAO", "mes": 2}).json()
    geo = cliente.get("/mapa/malha").json()

    com_fronteira = {f["properties"]["codigo_ibge"] for f in geo["features"]}
    no_mapa = {m["codigo_ibge"] for m in dados["municipios"]}

    assert no_mapa <= com_fronteira


@precisa_de_dados
def test_o_mes_muda_o_resultado():
    """Se o mês não alterasse nada, a sazonalidade não estaria sendo usada."""
    def altos(mes):
        return cliente.get("/mapa/brasil",
                           params={"grupo_desastre": "ESTIAGEM_SECA",
                                   "mes": mes}).json()["resumo"]["alto"]

    assert altos(3) != altos(9)


@precisa_de_dados
def test_tipo_inexistente_da_404():
    resposta = cliente.get("/mapa/brasil",
                           params={"grupo_desastre": "NAO_EXISTE", "mes": 2})
    assert resposta.status_code == 404


@precisa_de_dados
def test_mes_invalido_e_recusado():
    resposta = cliente.get("/mapa/brasil",
                           params={"grupo_desastre": "INUNDACAO", "mes": 13})
    assert resposta.status_code == 422


@precisa_de_dados
def test_segunda_chamada_usa_o_cache():
    """O mapa custa milhares de previsões; repetir a conta a cada clique é caro."""
    parametros = {"grupo_desastre": "GRANIZO", "mes": 5, "ano": 2026}
    cliente.get("/mapa/brasil", params=parametros)

    assert ("GRANIZO", 5, 2026) in modulo_app._cache_mapa


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------


def test_html_tem_os_elementos_do_mapa():
    html = (modulo_app.RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
    for identificador in ("mapa-svg", "mapa-tipo", "mapa-mes", "mapa-botao",
                          "mapa-legenda", "mapa-dica"):
        assert f'id="{identificador}"' in html


def test_js_desenha_sem_biblioteca_externa():
    """O projeto roda offline: nada de mapa vindo de CDN."""
    js = (modulo_app.RAIZ / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (modulo_app.RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")

    for proibido in ("leaflet", "mapbox", "openlayers", "cdn.", "unpkg", "jsdelivr"):
        assert proibido not in js.lower()
        assert proibido not in html.lower()
