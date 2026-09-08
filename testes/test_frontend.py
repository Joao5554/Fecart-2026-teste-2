"""
Testes da interface web.

O frontend precisa funcionar mesmo antes de a API responder, então ele repete
duas listas do esquema: os tipos de desastre e as cores de cada nível de risco.
Repetição pede vigilância — os testes abaixo falham se essas listas saírem de
sincronia com `src/esquema.py`, que continua sendo a fonte da verdade.
"""

import re
from pathlib import Path

import pytest

from src import esquema

PASTA = Path(__file__).resolve().parent.parent / "frontend"
ARQUIVO_JS = PASTA / "app.js"
ARQUIVO_HTML = PASTA / "index.html"
ARQUIVO_CSS = PASTA / "estilo.css"

pytestmark = pytest.mark.skipif(
    not ARQUIVO_JS.exists(), reason="interface web não encontrada em frontend/"
)


def _js() -> str:
    return ARQUIVO_JS.read_text(encoding="utf-8")


def _corpo_da_funcao(assinatura: str) -> str:
    """Devolve o corpo de uma função do app.js, da assinatura até o `}` final.

    Recorta até a primeira linha que é só um `}` na coluna zero, que é como o
    arquivo fecha suas funções. Antes esta função lia um número fixo de
    caracteres, e o teste passou a falhar quando um comentário empurrou o
    trecho procurado para fora da janela — falha de medição, não de código.
    """
    conteudo = _js()
    inicio = conteudo.index(assinatura)
    fim = conteudo.index("\n}\n", inicio)
    return conteudo[inicio:fim]


def _lista_do_js(nome: str) -> list[str]:
    """Lê uma constante de array de strings declarada no app.js."""
    trecho = re.search(rf"const {nome} = \[(.*?)\];", _js(), re.DOTALL)
    assert trecho, f"constante {nome} não encontrada em app.js"
    return re.findall(r'"([^"]+)"', trecho.group(1))


def test_tipos_de_desastre_batem_com_o_esquema():
    assert set(_lista_do_js("TIPOS_DESASTRE")) == set(esquema.GRUPOS_COBRADE), (
        "A lista de tipos em frontend/app.js divergiu de GRUPOS_COBRADE. "
        "Atualize as duas juntas."
    )


def test_cores_batem_com_o_esquema():
    trecho = re.search(r"const CORES = \{(.*?)\};", _js(), re.DOTALL)
    assert trecho
    cores = dict(re.findall(r"(\w+):\s*\"(#[0-9A-Fa-f]{6})\"", trecho.group(1)))
    assert cores == esquema.CORES_RISCO


def test_niveis_de_risco_aparecem_na_interface():
    for nivel in esquema.CLASSES_RISCO:
        assert f'"{nivel}"' in _js(), f"nível '{nivel}' não é tratado no app.js"


def test_formulario_e_preenchido_antes_de_chamar_a_api():
    """
    Os campos fixos precisam ser montados fora do try/catch da rede.

    Se dependessem da resposta da API, uma falha de conexão deixaria o
    formulário vazio — o defeito que este teste existe para não deixar voltar.
    """
    corpo = _corpo_da_funcao("async function iniciar()")

    posicao_tipos = corpo.index("preencherTipos(TIPOS_DESASTRE)")
    posicao_try = corpo.index("try {")
    assert posicao_tipos < posicao_try, (
        "preencherTipos precisa rodar ANTES do try/catch que fala com a API"
    )


def test_html_carrega_os_arquivos_certos():
    html = ARQUIVO_HTML.read_text(encoding="utf-8")
    assert 'href="estilo.css"' in html
    assert 'src="app.js"' in html
    assert ARQUIVO_CSS.exists()


def test_html_tem_os_campos_que_o_js_procura():
    html = ARQUIVO_HTML.read_text(encoding="utf-8")
    for identificador in ("busca", "tipo", "mes", "botao", "sugestoes",
                          "resultado", "barras", "grafico", "aviso-modelo"):
        assert f'id="{identificador}"' in html, f"falta id='{identificador}' no HTML"


def test_js_usa_apenas_endpoints_que_existem():
    """Evita chamada a uma rota que foi renomeada no backend."""
    from backend.app import app

    rotas = {getattr(r, "path", "") for r in app.routes}
    chamadas = set(re.findall(r'pedir\("(/[a-z/]*)"', _js()))

    for chamada in chamadas:
        assert chamada in rotas, f"app.js chama {chamada}, que não existe na API"


# --------------------------------------------------------------------------
# Menu de navegação
# --------------------------------------------------------------------------


def _html() -> str:
    return ARQUIVO_HTML.read_text(encoding="utf-8")


def _css() -> str:
    return ARQUIVO_CSS.read_text(encoding="utf-8")


def test_todo_item_do_menu_aponta_para_uma_secao_existente():
    """
    Um link para um id que não existe simplesmente não faz nada quando
    clicado — falha silenciosa, do tipo que ninguém percebe até a
    apresentação.
    """
    html = _html()
    menu = html[html.index('id="menu-itens"'):html.index("</ul>")]
    destinos = re.findall(r'href="#([\w-]+)"', menu)

    assert destinos, "o menu não tem nenhum item"
    for destino in destinos:
        assert f'id="{destino}"' in html, (
            f"o menu aponta para #{destino}, que não existe na página"
        )


def test_menu_cobre_todas_as_secoes_da_pagina():
    """Seção sem item no menu vira conteúdo que só se acha rolando."""
    html = _html()
    menu = html[html.index('id="menu-itens"'):html.index("</ul>")]
    no_menu = set(re.findall(r'href="#([\w-]+)"', menu))

    secoes = set(re.findall(r'<section id="([\w-]+)"', html))
    assert secoes <= no_menu, f"seções fora do menu: {sorted(secoes - no_menu)}"


def test_secoes_reservam_espaco_para_o_menu_fixo():
    """
    Sem `scroll-margin-top`, pular para uma seção a esconde atrás do menu
    fixo: o clique parece funcionar, mas o título fica coberto.
    """
    assert "scroll-margin-top" in _css()
    assert "position: sticky" in _css()


# --------------------------------------------------------------------------
# Tema claro e escuro
# --------------------------------------------------------------------------


def test_o_tema_e_aplicado_antes_do_app_js():
    """
    Se o tema só fosse aplicado pelo app.js, quem escolheu o modo escuro veria
    um lampejo branco a cada carregamento, enquanto o script baixa.
    """
    html = _html()
    assert html.index("fecart-tema") < html.index('src="app.js"'), (
        "o tema precisa ser aplicado por um script no <head>, antes do app.js"
    )
    assert 'id="botao-tema"' in html


def test_tema_escuro_redefine_as_variaveis_da_interface():
    css = _css()
    assert '[data-tema="escuro"]' in css

    escuro = css[css.index('[data-tema="escuro"]'):]
    escuro = escuro[:escuro.index("}")]

    for variavel in ("--tinta", "--papel", "--fundo", "--borda"):
        assert variavel in escuro, f"{variavel} não muda no tema escuro"


def test_tema_escuro_nao_mexe_nas_cores_do_risco():
    """
    Verde, amarelo e vermelho significam nível de risco. Quem aprendeu
    "vermelho = alto" no tema claro não pode ter de reaprender no escuro —
    e as barras e legendas recebem essas cores do app.js, que não sabe qual
    tema está ativo.
    """
    css = _css()
    escuro = css[css.index('[data-tema="escuro"]'):]
    escuro = escuro[:escuro.index("}")]

    for variavel in ("--verde:", "--amarelo:", "--vermelho:"):
        assert variavel not in escuro, (
            f"{variavel} muda no tema escuro, mas é cor de dado, não de decoração"
        )


def test_toda_variavel_usada_existe_no_tema_claro():
    """
    O tema claro é o padrão: uma variável só definida no escuro deixaria a
    regra sem valor nenhum na abertura normal da página.
    """
    css = _css()
    raiz = css[css.index(":root {"):css.index('[data-tema="escuro"]')]

    definidas = set(re.findall(r"(--[\w-]+):", raiz))
    usadas = set(re.findall(r"var\((--[\w-]+)", css))

    assert usadas <= definidas, f"usadas sem definir: {sorted(usadas - definidas)}"


# --------------------------------------------------------------------------
# Animação do fenômeno escolhido
# --------------------------------------------------------------------------


def _fenomeno_por_tipo() -> dict[str, str]:
    """Lê o de-para tipo -> fenômeno declarado no app.js."""
    trecho = re.search(r"const FENOMENO_POR_TIPO = \{(.*?)\};", _js(), re.DOTALL)
    assert trecho, "FENOMENO_POR_TIPO não encontrado em app.js"
    return dict(re.findall(r"(\w+):\s*\"(\w+)\"", trecho.group(1)))


def test_todo_tipo_de_desastre_tem_uma_animacao():
    """
    Um tipo fora do de-para não quebra nada — simplesmente não anima. É o tipo
    de falha que ninguém nota até alguém perguntar por que só a seca não tem
    efeito nenhum.
    """
    from src import esquema

    sem_animacao = set(esquema.GRUPOS_COBRADE) - set(_fenomeno_por_tipo())
    assert not sem_animacao, f"tipos sem animação: {sorted(sem_animacao)}"


def test_a_animacao_nao_inventa_tipo_que_nao_existe():
    from src import esquema

    inventados = set(_fenomeno_por_tipo()) - set(esquema.GRUPOS_COBRADE)
    assert not inventados, f"tipos que não existem no esquema: {sorted(inventados)}"


def test_todo_fenomeno_tem_regra_no_css_e_contagem_no_js():
    js, css = _js(), _css()
    fenomenos = set(_fenomeno_por_tipo().values())

    particulas = re.search(r"const PARTICULAS = \{(.*?)\};", js, re.DOTALL)
    assert particulas
    contados = set(re.findall(r"(\w+):", particulas.group(1)))

    for fenomeno in fenomenos:
        assert f'[data-fenomeno="{fenomeno}"]' in css, (
            f"o fenômeno '{fenomeno}' não tem regra de estilo"
        )
        assert fenomeno in contados, (
            f"o fenômeno '{fenomeno}' não diz quantas partículas usa"
        )


def test_toda_animacao_declarada_e_usada():
    """Regra de fenômeno no CSS sem tipo que a acione é código morto."""
    usados = set(_fenomeno_por_tipo().values())
    no_css = set(re.findall(r'\[data-fenomeno="(\w+)"\]', _css()))
    assert no_css == usados, f"sobrando no CSS: {sorted(no_css - usados)}"


def test_a_camada_de_animacao_nao_rouba_o_mouse():
    """
    Sem `pointer-events: none`, a camada fica na frente do mapa e a dica de
    cada município para de aparecer — o efeito visual quebraria a parte
    informativa da tela.
    """
    css = _css()
    bloco = css[css.index(".animacao-mapa {"):]
    bloco = bloco[:bloco.index("}")]
    assert "pointer-events: none" in bloco


def test_a_animacao_fica_atras_da_dica():
    """A dica precisa continuar legível por cima das partículas."""
    css = _css()

    def z_index(seletor):
        bloco = css[css.index(seletor):]
        bloco = bloco[:bloco.index("}")]
        return int(re.search(r"z-index:\s*(\d+)", bloco).group(1))

    assert z_index(".animacao-mapa {") < z_index(".mapa-dica {")


def test_os_tres_mapas_recebem_a_animacao():
    html, js = _html(), _js()
    for mapa in ("mapa", "cidade", "ano"):
        assert f'id="{mapa}-animacao"' in html, f"falta a camada no mapa '{mapa}'"
        assert f'aplicarAnimacao("{mapa}-animacao"' in js, (
            f"o mapa '{mapa}' nunca liga a animação"
        )


def test_a_animacao_avisa_que_e_ilustracao():
    """
    O site afirma não ser previsão meteorológica. Chuva sobre o mapa do Brasil
    se parece com uma, então o aviso ao lado da legenda precisa existir.
    """
    js, html = _js(), _html()
    assert "NOTA_ANIMACAO" in js
    for mapa in ("mapa", "cidade", "ano"):
        assert f'id="{mapa}-animacao-nota"' in html


def test_a_animacao_e_desligada_por_quem_pede_menos_movimento():
    css = _css()
    reduzido = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation: none !important" in reduzido[:200]


# --------------------------------------------------------------------------
# Camada de chuva medida
# --------------------------------------------------------------------------


def test_os_tres_mapas_tem_a_camada_de_chuva():
    html, js = _html(), _js()
    for mapa in ("mapa", "cidade", "ano"):
        for parte in ("chuva", "chuva-canvas", "chuva-legenda", "chuva-nota"):
            assert f'id="{mapa}-{parte}"' in html, f"falta {mapa}-{parte}"
        assert f'atualizarChuva("{mapa}")' in js, (
            f"o mapa '{mapa}' nunca redesenha a chuva"
        )


def test_o_canvas_da_chuva_acompanha_o_viewbox_do_mapa():
    """
    O canvas é posicionado sobre o SVG e recebe a projeção dele. Se as
    dimensões internas divergirem do viewBox, a chuva aparece deslocada do
    mapa — erro que passa despercebido porque as duas camadas *parecem*
    certas separadamente.
    """
    html = _html()
    for svg_id, canvas_id in [("mapa-svg", "mapa-chuva-canvas"),
                              ("cidade-svg", "cidade-chuva-canvas"),
                              ("ano-svg", "ano-chuva-canvas")]:
        svg = re.search(rf'id="{svg_id}" viewBox="0 0 (\d+) (\d+)"', html)
        assert svg, f"viewBox de {svg_id} não encontrado"

        canvas = re.search(
            rf'id="{canvas_id}"[^>]*?width="(\d+)" height="(\d+)"', html, re.DOTALL
        )
        assert canvas, f"dimensões de {canvas_id} não encontradas"
        assert svg.groups() == canvas.groups(), (
            f"{canvas_id} ({canvas.groups()}) não casa com "
            f"{svg_id} ({svg.groups()})"
        )


def test_a_camada_de_chuva_nao_intercepta_o_mouse():
    css = _css()
    bloco = css[css.index(".camada-chuva {"):]
    bloco = bloco[:bloco.index("}")]
    assert "pointer-events: none" in bloco


def test_a_chuva_fica_entre_o_mapa_e_a_animacao():
    """Sobre o mapa, mas sob a animação e a dica — nesta ordem."""
    css = _css()

    def z_index(seletor):
        bloco = css[css.index(seletor):]
        bloco = bloco[:bloco.index("}")]
        return int(re.search(r"z-index:\s*(\d+)", bloco).group(1))

    assert z_index(".camada-chuva {") < z_index(".animacao-mapa {")
    assert z_index(".animacao-mapa {") < z_index(".mapa-dica {")


def test_o_mapa_e_atenuado_quando_a_chuva_entra():
    """
    Duas escalas de cor cheias na mesma área não se leem. Com a chuva
    ligada, o mapa embaixo precisa virar referência geográfica.
    """
    assert ".mapa-area.com-chuva svg path" in _css()
    assert 'classList.add("com-chuva")' in _js()
    assert 'classList.remove("com-chuva")' in _js()


def test_a_camada_diz_de_que_periodo_e_a_medicao():
    """
    O mapa de risco prevê um ano que ainda não aconteceu; a chuva ao lado é
    sempre de outro período. Omitir isso faria parecer previsão do tempo.
    """
    js = _js()
    assert "dados.periodo" in js
    assert "interpolado" in js, "o rodapé precisa avisar o que é interpolação"


def test_a_interpolacao_roda_numa_grade_pequena():
    """
    Calcular direto nos 640×640 pixels seriam 400 mil células × 600 estações
    e a página congelaria. A grade pequena é ampliada pelo navegador.
    """
    js = _js()
    grade = re.search(r"const GRADE_CHUVA = (\d+);", js)
    assert grade, "GRADE_CHUVA não encontrada"
    assert int(grade.group(1)) <= 128, "grade grande demais para calcular no navegador"
    assert "imageSmoothingEnabled = true" in js
