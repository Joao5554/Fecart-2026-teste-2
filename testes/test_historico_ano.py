"""
Testes do histórico por ano — os endpoints que alimentam o mapa "ano a ano".

Estes endpoints não passam pelo modelo: respondem só o que o Atlas registrou.
É a diferença que os testes abaixo protegem, porque ela muda a leitura do
mapa. O mapa de risco mostra uma estimativa, que pode errar; este mostra um
fato, e um fato que aparecesse colorido pela escala de risco convidaria
qualquer visitante a confundir os dois.
"""

from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_OCORRENCIAS = RAIZ / "dados" / "ocorrencias.csv"

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from backend.app import FAIXAS_OCORRENCIAS, app  # noqa: E402

cliente = fastapi_testclient.TestClient(app)

precisa_do_atlas = pytest.mark.skipif(
    not ARQUIVO_OCORRENCIAS.exists(),
    reason="ocorrências não preparadas — rode: python dados/preparar_dados.py",
)


@pytest.fixture(scope="module")
def anos():
    return cliente.get("/historico/anos").json()


@pytest.fixture(scope="module")
def ano_recente(anos):
    return cliente.get(f"/historico/ano/{anos['ultimo_ano']}").json()


# --------------------------------------------------------------------------
# Lista de anos
# --------------------------------------------------------------------------


@precisa_do_atlas
def test_lista_de_anos_cobre_a_serie_inteira(anos):
    assert anos["primeiro_ano"] == 1991
    assert anos["ultimo_ano"] >= 2025
    esperados = anos["ultimo_ano"] - anos["primeiro_ano"] + 1
    assert len(anos["anos"]) == esperados, "há buraco na série de anos"


@precisa_do_atlas
def test_lista_de_anos_vem_em_ordem(anos):
    valores = [a["ano"] for a in anos["anos"]]
    assert valores == sorted(valores)


@precisa_do_atlas
def test_todo_ano_tem_ocorrencia(anos):
    """Ano sem nenhum registro viraria uma opção que só devolve erro 404."""
    vazios = [a["ano"] for a in anos["anos"] if a["ocorrencias"] == 0]
    assert not vazios, f"anos sem ocorrência no seletor: {vazios}"


# --------------------------------------------------------------------------
# Um ano
# --------------------------------------------------------------------------


@precisa_do_atlas
def test_ano_traz_o_que_o_mapa_precisa(ano_recente):
    for campo in ("ano", "total_ocorrencias", "municipios_atingidos", "mortos",
                  "afetados", "por_mes", "por_tipo", "por_uf", "legenda",
                  "municipios"):
        assert campo in ano_recente, f"falta '{campo}' na resposta"

    assert len(ano_recente["por_mes"]) == 12
    assert ano_recente["municipios"], "nenhum município no ano mais recente"


@precisa_do_atlas
def test_totais_batem_com_a_lista_de_municipios(ano_recente):
    """O resumo e a lista precisam contar a mesma coisa."""
    municipios = ano_recente["municipios"]

    assert len(municipios) == ano_recente["municipios_atingidos"]
    assert sum(m["ocorrencias"] for m in municipios) \
        == ano_recente["total_ocorrencias"]
    assert sum(m["mortos"] for m in municipios) == ano_recente["mortos"]
    assert sum(ano_recente["por_mes"]) == ano_recente["total_ocorrencias"]
    assert sum(t["ocorrencias"] for t in ano_recente["por_tipo"]) \
        == ano_recente["total_ocorrencias"]
    assert sum(u["ocorrencias"] for u in ano_recente["por_uf"]) \
        == ano_recente["total_ocorrencias"]


@precisa_do_atlas
def test_cada_municipio_aparece_uma_vez_so(ano_recente):
    """Repetido, o município seria desenhado duas vezes por cima de si mesmo."""
    codigos = [m["codigo_ibge"] for m in ano_recente["municipios"]]
    assert len(codigos) == len(set(codigos))


@precisa_do_atlas
def test_a_cor_corresponde_a_faixa_de_ocorrencias(ano_recente):
    """
    A cor é decidida no servidor. Se ela não seguir a legenda que o próprio
    servidor manda junto, o mapa fica bonito e mentiroso: um município com 10
    ocorrências apareceria na cor de quem teve uma.
    """
    faixas = {(f["de"], f["ate"]): f["cor"] for f in ano_recente["legenda"]}

    def cor_esperada(quantidade):
        for (de, ate), cor in faixas.items():
            if quantidade >= de and (ate is None or quantidade <= ate):
                return cor
        return None

    fora = [m for m in ano_recente["municipios"]
            if m["cor"] != cor_esperada(m["ocorrencias"])]
    assert not fora, f"{len(fora)} município(s) com cor fora da faixa: {fora[:3]}"


@precisa_do_atlas
def test_a_escala_do_ano_nao_se_confunde_com_a_do_risco(ano_recente):
    """
    Verde, amarelo e vermelho significam nível de risco no resto do site.
    Reaproveitá-los para contar ocorrências faria o visitante ler uma
    contagem do passado como se fosse uma previsão.
    """
    from src import esquema

    do_risco = {c.upper() for c in esquema.CORES_RISCO.values()}
    do_ano = {f["cor"].upper() for f in ano_recente["legenda"]}
    assert not (do_ano & do_risco), "as duas escalas usam a mesma cor"


@precisa_do_atlas
def test_municipios_vem_do_maior_para_o_menor(ano_recente):
    contagens = [m["ocorrencias"] for m in ano_recente["municipios"]]
    assert contagens == sorted(contagens, reverse=True)


@precisa_do_atlas
def test_numeros_conferem_com_o_csv_do_atlas(ano_recente):
    """
    A conferência que importa: o total do endpoint bate com uma contagem
    feita direto no arquivo, sem passar pela API.
    """
    bruto = pd.read_csv(ARQUIVO_OCORRENCIAS)
    do_ano = bruto[bruto["ano"] == ano_recente["ano"]]

    assert ano_recente["total_ocorrencias"] == len(do_ano)
    assert ano_recente["municipios_atingidos"] == do_ano["codigo_ibge"].nunique()
    assert ano_recente["mortos"] == int(do_ano["mortos"].sum())


# --------------------------------------------------------------------------
# Filtro por tipo
# --------------------------------------------------------------------------


@precisa_do_atlas
def test_filtro_por_tipo_reduz_o_resultado(ano_recente):
    tipo = ano_recente["por_tipo"][0]["grupo_desastre"]
    filtrado = cliente.get(
        f"/historico/ano/{ano_recente['ano']}?grupo_desastre={tipo}"
    ).json()

    assert filtrado["total_ocorrencias"] == ano_recente["por_tipo"][0]["ocorrencias"]
    assert filtrado["total_ocorrencias"] <= ano_recente["total_ocorrencias"]
    assert [t["grupo_desastre"] for t in filtrado["por_tipo"]] == [tipo]
    for municipio in filtrado["municipios"]:
        assert municipio["tipos"] == [tipo]


@precisa_do_atlas
def test_soma_dos_tipos_reconstroi_o_ano(ano_recente):
    """Filtrar por cada tipo e somar tem que devolver o ano inteiro."""
    total = 0
    for linha in ano_recente["por_tipo"]:
        parte = cliente.get(
            f"/historico/ano/{ano_recente['ano']}"
            f"?grupo_desastre={linha['grupo_desastre']}"
        ).json()
        total += parte["total_ocorrencias"]

    assert total == ano_recente["total_ocorrencias"]


# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------


@precisa_do_atlas
def test_ano_fora_da_serie_explica_o_periodo_disponivel():
    resposta = cliente.get("/historico/ano/1700")

    assert resposta.status_code == 404
    detalhe = resposta.json()["detail"]
    assert "1700" in detalhe
    assert "1991" in detalhe, "a mensagem precisa dizer qual período existe"


@precisa_do_atlas
def test_tipo_inexistente_devolve_404(ano_recente):
    resposta = cliente.get(
        f"/historico/ano/{ano_recente['ano']}?grupo_desastre=CHUVA_DE_SAPOS"
    )
    assert resposta.status_code == 404


# --------------------------------------------------------------------------
# A escala de cor
# --------------------------------------------------------------------------


def test_as_faixas_cobrem_qualquer_contagem():
    """Sem buraco nem sobreposição: toda contagem cai em exatamente uma faixa."""
    for quantidade in range(1, 200):
        casam = [
            (minimo, maximo) for minimo, maximo, _, _ in FAIXAS_OCORRENCIAS
            if quantidade >= minimo and (maximo is None or quantidade <= maximo)
        ]
        assert len(casam) == 1, f"{quantidade} ocorrências casam com {casam}"


def test_as_faixas_ficam_mais_escuras_conforme_sobem():
    """A escala precisa ser lida sem legenda: mais escuro = mais ocorrências."""
    def luminosidade(cor):
        r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    tons = [luminosidade(cor) for _, _, cor, _ in FAIXAS_OCORRENCIAS]
    assert tons == sorted(tons, reverse=True), "a escala não escurece de forma monótona"
