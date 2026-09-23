"""
Testes do mapa de risco.

O risco silencioso aqui é o mapa desenhar bonito e mentir: polígono casado com
o município errado, ou município sem histórico pintado de verde como se fosse
seguro. Os testes cobrem essas duas coisas.
"""

import json

import numpy
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
precisa_de_malha_estados = pytest.mark.skipif(
    not modulo_app.ARQUIVO_MALHA_ESTADOS.exists(),
    reason="rode: python dados/baixar_malha_estados.py",
)
precisa_de_relevo = pytest.mark.skipif(
    not (modulo_app.ARQUIVO_RELEVO.exists()
         and modulo_app.ARQUIVO_RELEVO_META.exists()),
    reason="rode: python dados/baixar_relevo.py",
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
# Capitais
# --------------------------------------------------------------------------


def test_o_esquema_traz_as_27_capitais():
    """Uma UF sem capital deixaria um estado inteiro sem ponto de referência."""
    assert set(esquema.CAPITAIS) == set(esquema.UFS)


@precisa_de_malha
def test_toda_capital_existe_na_malha():
    """
    O marcador é posicionado a partir do polígono do município. Código que
    não existe na malha vira capital sem lugar no mapa — some sem erro
    nenhum, que é o tipo de falha que ninguém percebe.
    """
    geo = cliente.get("/mapa/malha").json()
    codigos = {f["properties"]["codigo_ibge"] for f in geo["features"]}

    faltando = [uf for uf, (codigo, _) in esquema.CAPITAIS.items()
                if codigo not in codigos]
    assert not faltando, f"capitais fora da malha: {faltando}"


@precisa_de_malha
def test_capitais_devolvem_ponto_dentro_do_brasil():
    resposta = cliente.get("/mapa/capitais")
    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["total"] == 27

    for capital in dados["capitais"]:
        assert -34 <= capital["lat"] <= 6, capital
        assert -74 <= capital["lon"] <= -34, capital
        assert capital["nome"]
        assert capital["uf"] in esquema.UFS


@precisa_de_malha
def test_o_ponto_da_capital_cai_perto_da_cidade():
    """
    O centroide do maior polígono precisa cair sobre o município, e não sobre
    a média dos vértices de um contorno recortado. Duas capitais de posição
    conhecida bastam para pegar uma troca de latitude por longitude, que é o
    erro que mais aparece em código de mapa.
    """
    por_uf = {c["uf"]: c for c in cliente.get("/mapa/capitais").json()["capitais"]}

    # Brasília fica em torno de -15,8 / -47,9; Manaus, de -3,1 / -60,0.
    assert abs(por_uf["DF"]["lat"] - (-15.8)) < 1
    assert abs(por_uf["DF"]["lon"] - (-47.9)) < 1
    assert abs(por_uf["AM"]["lat"] - (-3.1)) < 1.5
    assert abs(por_uf["AM"]["lon"] - (-60.0)) < 1.5


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


# --------------------------------------------------------------------------
# Fronteiras dos estados
# --------------------------------------------------------------------------


@precisa_de_malha_estados
def test_malha_dos_estados_tem_as_27_unidades():
    resposta = cliente.get("/mapa/estados")
    assert resposta.status_code == 200

    geo = resposta.json()
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 27, "o Brasil tem 26 estados e o DF"


@precisa_de_malha_estados
def test_cada_estado_traz_sigla_codigo_e_nome():
    """Sem a sigla não há como casar a fronteira com o seletor de estado."""
    geo = cliente.get("/mapa/estados").json()

    for feicao in geo["features"]:
        propriedades = feicao["properties"]
        assert len(propriedades["sigla"]) == 2
        assert propriedades["sigla"].isupper()
        assert 11 <= propriedades["codigo_uf"] <= 53
        assert propriedades["nome"]


@precisa_de_malha_estados
def test_as_siglas_dos_estados_nao_se_repetem():
    geo = cliente.get("/mapa/estados").json()
    siglas = [f["properties"]["sigla"] for f in geo["features"]]
    assert len(siglas) == len(set(siglas))
    assert "??" not in siglas, "algum código do IBGE não foi reconhecido"


@precisa_de_malha_estados
def test_fronteira_dos_estados_cai_dentro_do_brasil():
    """
    O mesmo cuidado da malha municipal: latitude e longitude trocadas jogariam
    o país no oceano Índico, e aqui o erro seria ainda mais discreto — são 27
    contornos desenhados por cima de um mapa que continuaria certo.
    """
    geo = cliente.get("/mapa/estados").json()

    def pontos(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for parte in coords:
                yield from pontos(parte)

    for feicao in geo["features"]:
        for lon, lat in pontos(feicao["geometry"]["coordinates"]):
            assert -75 <= lon <= -33, f"longitude fora do Brasil: {lon}"
            assert -34 <= lat <= 6, f"latitude fora do Brasil: {lat}"


@precisa_de_malha_estados
@precisa_de_malha
def test_as_duas_malhas_batem_no_continente():
    """
    A fronteira dos estados é desenhada POR CIMA da malha municipal. Se as duas
    vierem de simplificações diferentes do IBGE, a linha do estado passa ao
    lado da divisa do município e o mapa ganha uma fresta — discreta no país
    inteiro, gritante quando a câmera desce num estado.

    A comparação exclui as ilhas oceânicas de propósito. A malha de UF do IBGE
    não as traz, e a municipal traz: Fernando de Noronha, distrito de
    Pernambuco, está a -32,4° de longitude e sozinho move o extremo leste em
    2,4°. A consequência prática é só essa — Noronha aparece no mapa, pintado
    com seu risco, mas sem contorno de estado em volta.
    """
    def extremos(geo):
        lons, lats = [], []

        def andar(coords):
            if isinstance(coords[0], (int, float)):
                if coords[0] < -34.0:          # descarta as ilhas oceânicas
                    lons.append(coords[0])
                    lats.append(coords[1])
            else:
                for parte in coords:
                    andar(parte)

        for feicao in geo["features"]:
            andar(feicao["geometry"]["coordinates"])
        return min(lons), max(lons), min(lats), max(lats)

    municipios = extremos(cliente.get("/mapa/malha").json())
    estados = extremos(cliente.get("/mapa/estados").json())

    for do_municipio, do_estado in zip(municipios, estados):
        assert abs(do_municipio - do_estado) < 0.05, (
            f"as duas malhas não batem ({do_municipio} contra {do_estado}); "
            "baixe as duas com qualidade=minima"
        )


@precisa_de_malha_estados
@precisa_de_malha
def test_as_ilhas_oceanicas_ficam_sem_contorno_de_estado():
    """
    O contrário do teste acima: fixa a diferença conhecida entre as duas
    malhas, para ela não passar despercebida se um dia mudar. Se o IBGE
    começar a devolver as ilhas na malha de UF, este teste falha e o de cima
    pode largar o filtro.
    """
    def mais_a_leste(geo):
        maior = -180.0

        def andar(coords):
            nonlocal maior
            if isinstance(coords[0], (int, float)):
                maior = max(maior, coords[0])
            else:
                for parte in coords:
                    andar(parte)

        for feicao in geo["features"]:
            andar(feicao["geometry"]["coordinates"])
        return maior

    assert mais_a_leste(cliente.get("/mapa/malha").json()) > -33.0, (
        "a malha municipal deixou de trazer Fernando de Noronha"
    )
    assert mais_a_leste(cliente.get("/mapa/estados").json()) < -34.0, (
        "a malha de UF passou a trazer as ilhas: revise o teste anterior"
    )


# --------------------------------------------------------------------------
# Relevo
# --------------------------------------------------------------------------


@precisa_de_relevo
def test_metadados_do_relevo_descrevem_a_grade():
    resposta = cliente.get("/mapa/relevo")
    assert resposta.status_code == 200

    meta = resposta.json()
    assert meta["largura"] > 500 and meta["altura"] > 500
    assert 0 < meta["passo_graus"] <= 0.1
    assert meta["lon_oeste"] < -70 and meta["lat_norte"] > 5
    assert meta["url_grade"] == "/mapa/relevo.bin"
    assert meta["fonte"], "a grade precisa dizer de onde veio"


@precisa_de_relevo
def test_a_grade_tem_o_tamanho_que_os_metadados_prometem():
    """
    O arquivo vai cru, sem cabeçalho: o navegador confia no que os metadados
    dizem para saber onde uma linha acaba e a outra começa. Um descompasso de
    um único ponto entre os dois inclinaria o Brasil inteiro na tela.
    """
    meta = cliente.get("/mapa/relevo").json()
    corpo = cliente.get("/mapa/relevo.bin").content

    assert len(corpo) == meta["largura"] * meta["altura"] * 2
    assert len(corpo) == meta["bytes"]


@precisa_de_relevo
def test_o_relevo_nao_tem_altitude_abaixo_do_nivel_do_mar():
    """
    A batimetria do oceano foi zerada de propósito. Se voltar, a linha da costa
    vira um degrau de 4 km e o sombreamento desenha um risco brilhante em cima
    de todo o litoral.
    """
    grade = numpy.frombuffer(cliente.get("/mapa/relevo.bin").content,
                             dtype="<i2")
    assert grade.min() == 0, "há profundidade negativa na grade"
    assert grade.max() < 7000, "altitude impossível: a Terra não tem isso"


@precisa_de_relevo
def test_altitudes_conhecidas_batem_com_a_realidade():
    """
    O erro silencioso do relevo é a grade sair espelhada ou deslocada: continua
    parecendo relevo, e ninguém nota que o planalto central foi parar no mar.
    Quatro pontos de altitude conhecida pegam isso.

    As margens são largas porque cada ponto da grade é a média de ~4,4 km de
    terreno: um cume estreito sempre sai mais baixo que a altitude de placa.
    """
    meta = cliente.get("/mapa/relevo").json()
    grade = numpy.frombuffer(cliente.get("/mapa/relevo.bin").content,
                             dtype="<i2").reshape(meta["altura"], meta["largura"])

    def altitude(lat, lon):
        linha = round((meta["lat_norte"] - lat) / meta["passo_graus"])
        coluna = round((lon - meta["lon_oeste"]) / meta["passo_graus"])
        return int(grade[linha, coluna])

    # (nome, lat, lon, mínimo, máximo)
    pontos = [
        ("Brasília, no planalto central", -15.79, -47.88, 800, 1300),
        ("Manaus, na planície amazônica", -3.10, -60.02, 0, 250),
        ("Campos do Jordão, na Mantiqueira", -22.74, -45.59, 1100, 2200),
        ("Recife, no litoral", -8.05, -34.88, 0, 250),
    ]

    for nome, lat, lon, minimo, maximo in pontos:
        metros = altitude(lat, lon)
        assert minimo <= metros <= maximo, (
            f"{nome}: a grade diz {metros} m, esperava entre {minimo} e {maximo}"
        )


@precisa_de_relevo
def test_a_planicie_e_mais_baixa_que_o_planalto():
    """
    Um teste de forma, e não de ponto: mesmo que toda a grade estivesse
    deslocada por igual, a Amazônia continuaria tendo de ser mais baixa que o
    centro do país. É o que separa "relevo com erro de escala" de "relevo que
    não é relevo nenhum".
    """
    meta = cliente.get("/mapa/relevo").json()
    grade = numpy.frombuffer(cliente.get("/mapa/relevo.bin").content,
                             dtype="<i2").reshape(meta["altura"], meta["largura"])

    def media(lat1, lat2, lon1, lon2):
        linha1 = round((meta["lat_norte"] - lat1) / meta["passo_graus"])
        linha2 = round((meta["lat_norte"] - lat2) / meta["passo_graus"])
        coluna1 = round((lon1 - meta["lon_oeste"]) / meta["passo_graus"])
        coluna2 = round((lon2 - meta["lon_oeste"]) / meta["passo_graus"])
        return float(grade[linha1:linha2, coluna1:coluna2].mean())

    amazonia = media(-2.0, -5.0, -64.0, -58.0)
    planalto = media(-14.0, -18.0, -50.0, -45.0)

    assert amazonia < 200, f"a planície amazônica saiu a {amazonia:.0f} m"
    assert planalto > 500, f"o planalto central saiu a {planalto:.0f} m"
    assert planalto > amazonia + 400
