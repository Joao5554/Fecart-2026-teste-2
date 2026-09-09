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


PALCOS = ("abertura", "mapas", "despedida")


def test_cada_palco_existe_e_tem_como_ser_alcancado():
    """
    A página é uma sequência de três telas cheias, e cada uma só aparece
    quando `data-palco` no <body> muda. Um palco sem regra de CSS que o acenda
    fica invisível para sempre; um botão que aponte para um palco que não
    existe não faz nada quando clicado — falha silenciosa, do tipo que só
    aparece na hora da apresentação.
    """
    html, css, js = _html(), _css(), _js()

    for palco in PALCOS:
        assert f'id="palco-{palco}"' in html, f"o palco {palco} não existe"
        assert f'body[data-palco="{palco}"]' in css, (
            f"nenhuma regra de CSS acende o palco {palco}"
        )
        assert f'trocarPalco("{palco}")' in js, (
            f"nenhum botão leva ao palco {palco}"
        )


def test_toda_secao_esta_dentro_de_um_palco_ou_da_gaveta():
    """
    Seção solta fora dos palcos não é alcançável por nenhum caminho: a página
    não rola, e o que está fora de um palco simplesmente nunca é mostrado.
    """
    html = _html()

    # Onde cada contêiner que pode conter seções começa, em ordem no arquivo.
    recipientes = [html.index(f'id="palco-{p}"') for p in PALCOS]
    recipientes.append(html.index('id="gaveta"'))

    for secao in re.finditer(r'<section id="([\w-]+)"', html):
        assert any(inicio < secao.start() for inicio in recipientes), (
            f"a seção {secao.group(1)} está fora de qualquer palco"
        )


def test_as_abas_apontam_para_mapas_que_existem():
    """
    Cada aba troca o mapa em cena e o bloco de controles junto. Se qualquer um
    dos dois faltar, a aba deixa a tela pela metade — com o mapa novo e os
    controles do antigo, ou sem mapa nenhum.
    """
    html = _html()
    abas = re.findall(r'class="aba[^"]*"[^>]*data-mapa="([\w-]+)"', html)

    assert set(abas) == {"mapa", "ano"}, f"abas encontradas: {abas}"
    for aba in abas:
        assert f'id="teatro-{aba}"' in html, f"a aba {aba} não tem teatro"
        assert f'id="controles-{aba}"' in html, f"a aba {aba} não tem controles"


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


def _bloco_do_tema_claro() -> str:
    """O bloco de variáveis que o tema claro redefine."""
    css = _css()
    inicio = css.index('[data-tema="claro"] {')
    return css[inicio:css.index("}", inicio)]


def test_tema_claro_redefine_as_variaveis_da_interface():
    """
    O padrão passou a ser o escuro, porque os palcos têm um céu estrelado e um
    campo de vento por trás e a interface clara sobre eles apagaria a animação
    inteira. O tema claro virou a exceção — e precisa redefinir tudo o que dá
    contraste, senão sobra texto claro sobre fundo claro.
    """
    for variavel in ("--tinta", "--papel", "--fundo", "--borda"):
        assert variavel in _bloco_do_tema_claro(), (
            f"{variavel} não muda no tema claro"
        )


def test_tema_claro_nao_mexe_nas_cores_do_risco():
    """
    Verde, amarelo e vermelho significam nível de risco. Quem aprendeu
    "vermelho = alto" num tema não pode ter de reaprender no outro — e as
    barras e legendas recebem essas cores do app.js, que não sabe qual tema
    está ativo.
    """
    for variavel in ("--verde:", "--amarelo:", "--vermelho:"):
        assert variavel not in _bloco_do_tema_claro(), (
            f"{variavel} muda no tema claro, mas é cor de dado, não de decoração"
        )


# Variáveis que existem de propósito fora do `:root`, com um valor por
# elemento. `--zoom` é a escala corrente da câmera de cada mapa: o app.js a
# reescreve a cada quadro do voo, e é ela que mantém a espessura dos traços
# constante na tela em qualquer altura.
VARIAVEIS_LOCAIS = {"--zoom"}


def test_toda_variavel_usada_existe_no_tema_padrao():
    """
    O `:root` é o tema padrão: uma variável só definida no tema claro deixaria
    a regra sem valor nenhum na abertura normal da página.
    """
    css = _css()
    raiz = css[css.index(":root {"):css.index('[data-tema="claro"]')]

    definidas = set(re.findall(r"(--[\w-]+):", raiz)) | VARIAVEIS_LOCAIS
    usadas = set(re.findall(r"var\((--[\w-]+)", css))

    assert usadas <= definidas, f"usadas sem definir: {sorted(usadas - definidas)}"


def test_variavel_local_e_definida_antes_de_ser_usada():
    """
    `--zoom` tem um valor de partida no CSS além do que o app.js escreve: sem
    ele, a primeira pintura — antes de a câmera existir — calcularia uma
    divisão por nada e o mapa entraria sem fronteira nenhuma.
    """
    assert "--zoom: 1;" in _css()


# --------------------------------------------------------------------------
# Capitais
# --------------------------------------------------------------------------


MAPAS = ("consulta", "mapa", "cidade", "ano")


def test_todos_os_mapas_marcam_as_capitais():
    html, js = _html(), _js()
    for mapa in MAPAS:
        assert f'id="{mapa}-capitais-svg"' in html, (
            f"o mapa '{mapa}' não tem camada de capitais"
        )
        assert f'id="{mapa}-capitais"' in html, (
            f"o mapa '{mapa}' não tem o interruptor das capitais"
        )
    assert "camadaDeCapitais(" in js


def test_a_camada_das_capitais_acompanha_o_viewbox_do_mapa():
    """
    A camada é posicionada sobre o mapa e recebe a projeção dele. Com
    dimensões diferentes, os marcadores aparecem deslocados das cidades que
    nomeiam — e um marcador deslocado é pior do que marcador nenhum.
    """
    html = _html()
    for mapa in MAPAS:
        svg_id, capitais_id = f"{mapa}-svg", f"{mapa}-capitais-svg"
        mapa = re.search(rf'id="{svg_id}" viewBox="0 0 (\d+) (\d+)"', html)
        assert mapa, f"viewBox de {svg_id} não encontrado"

        camada = re.search(
            rf'id="{capitais_id}"[^>]*?viewBox="0 0 (\d+) (\d+)"', html, re.DOTALL
        )
        assert camada, f"viewBox de {capitais_id} não encontrado"
        assert mapa.groups() == camada.groups(), (
            f"{capitais_id} ({camada.groups()}) não casa com "
            f"{svg_id} ({mapa.groups()})"
        )


def test_a_camada_das_capitais_nao_rouba_o_mouse():
    """
    A dica de cada município vem de um listener no <svg> de baixo, que procura
    o `path` sob o mouse. Sem `pointer-events: none`, a camada de cima captura
    o evento e a dica some justamente em cima das capitais.
    """
    css = _css()
    bloco = css[css.index(".camada-capitais {"):]
    bloco = bloco[:bloco.index("}")]
    assert "pointer-events: none" in bloco


def test_as_capitais_ficam_acima_da_chuva_e_abaixo_da_dica():
    """
    Dentro do mapa as capitais ficariam sob a camada de chuva, e o nome sumiria
    justamente quando a chuva está ligada. Acima da dica, cobririam o texto.
    """
    css = _css()

    def z_index(seletor):
        bloco = css[css.index(seletor):]
        bloco = bloco[:bloco.index("}")]
        return int(re.search(r"z-index:\s*(\d+)", bloco).group(1))

    assert z_index(".camada-chuva {") < z_index(".camada-capitais {")
    assert z_index(".camada-capitais {") < z_index(".mapa-dica {")


def test_o_interruptor_das_capitais_comeca_ligado():
    """
    O marcador é referência geográfica: quem abre o mapa pela primeira vez
    precisa dele para achar onde está olhando. Desligar é a exceção.
    """
    html = _html()
    for mapa in MAPAS:
        marcacao = re.search(rf'<input type="checkbox" id="{mapa}-capitais"([^>]*)>',
                             html)
        assert marcacao, f"interruptor de {mapa} não encontrado"
        assert "checked" in marcacao.group(1), (
            f"o interruptor das capitais de '{mapa}' começa desligado"
        )


def test_a_pagina_nao_tem_mais_a_animacao_decorativa():
    """
    Chuva animada sobre o mapa parecia previsão do tempo, e disputava a
    leitura com a camada de chuva medida — que é dado. Saiu; este teste
    existe para não voltar por descuido.
    """
    js, css, html = _js(), _css(), _html()
    assert "aplicarAnimacao" not in js
    assert "FENOMENO_POR_TIPO" not in js
    assert "data-fenomeno" not in css
    assert "animacao-mapa" not in html


# --------------------------------------------------------------------------
# Camada de chuva medida
# --------------------------------------------------------------------------


def test_todos_os_mapas_tem_a_camada_de_chuva():
    html, js = _html(), _js()
    for mapa in MAPAS:
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
    for mapa in MAPAS:
        svg_id, canvas_id = f"{mapa}-svg", f"{mapa}-chuva-canvas"
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


def test_a_chuva_fica_entre_o_mapa_e_a_dica():
    """Sobre o mapa, mas sob a dica — que precisa continuar legível."""
    css = _css()

    def z_index(seletor):
        bloco = css[css.index(seletor):]
        bloco = bloco[:bloco.index("}")]
        return int(re.search(r"z-index:\s*(\d+)", bloco).group(1))

    assert z_index(".camada-chuva {") < z_index(".mapa-dica {")


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


def test_a_chuva_e_recortada_no_contorno_do_mapa():
    """
    Interpolar entre estações espalha valor por todo o retângulo do desenho,
    inclusive sobre o mar e sobre os estados que ficaram de fora do recorte.
    A máscara é o que impede a camada de afirmar chuva onde não há nem terra
    nem estação.
    """
    js = _js()
    assert "mascaraDoMapa" in js
    assert "new Path2D" in js
    assert "contexto.clip(" in js


def test_a_escala_de_chuva_e_continua():
    """
    Pintar faixa a faixa desenha degraus onde a chuva é contínua, e degrau no
    meio da mancha parece fronteira de dado. As cores são as mesmas da
    legenda; o que muda é que o valor entre duas faixas é interpolado.
    """
    js = _js()
    assert "rampaDeChuva" in js
    corpo = _corpo_da_funcao("function corDaChuva(")
    assert "depois.cor[c] - antes.cor[c]" in corpo, (
        "corDaChuva voltou a escolher uma faixa em vez de interpolar"
    )


# --------------------------------------------------------------------------
# Mapa dentro da seção de consulta
# --------------------------------------------------------------------------


def test_o_mapa_da_consulta_fica_no_painel_do_resultado():
    """
    O mapa responde à pergunta que acabou de ser feita, e fica junto do
    resultado dela — no painel da direita, logo abaixo do selo de risco. Solto
    em qualquer outro canto ele vira mais um mapa perdido na tela.
    """
    html = _html()
    painel = html[html.index('id="painel"'):html.index('id="palco-despedida"')]
    for identificador in ("consulta-mapa", "consulta-svg", "consulta-dica",
                          "consulta-legenda", "consulta-capitais-svg",
                          "consulta-chuva-canvas"):
        assert f'id="{identificador}"' in painel, (
            f"{identificador} não está dentro do painel do resultado"
        )


def test_o_mapa_da_consulta_nao_pede_previsao_de_novo():
    """
    A cor e a probabilidade já vieram na resposta que preencheu o selo do
    resultado. Pedir tudo outra vez custaria alguns segundos para desenhar
    exatamente o mesmo número.
    """
    corpo = _corpo_da_funcao("async function mostrarMapaDaConsulta(")
    assert "/prever" not in corpo, (
        "mostrarMapaDaConsulta refaz a previsão em vez de usar a que já tem"
    )
    assert "previsao.cor" in corpo and "previsao.probabilidades" in corpo


def test_trocar_de_municipio_apaga_o_mapa_da_consulta():
    """
    O contorno de Petrópolis embaixo do nome de Blumenau é pior do que mapa
    nenhum: mostra a cidade errada com cara de resposta certa.
    """
    corpo = _corpo_da_funcao('$("busca").addEventListener("input"')
    assert 'consulta-mapa").classList.add("oculto")' in corpo


# --------------------------------------------------------------------------
# Câmera: o voo do Brasil até o município
# --------------------------------------------------------------------------


def test_os_mapas_grandes_desenham_sempre_o_pais_inteiro():
    """
    O recorte por estado é trabalho da câmera, não do desenho. Se estes mapas
    voltassem a filtrar as feições por UF, aproximar uma cidade exigiria
    redesenhar 5.570 polígonos e o voo perderia o ponto de partida — não
    haveria mais um Brasil de onde sair.
    """
    for funcao in ("async function desenharMapa(",
                   "async function desenharMapaDoAno("):
        corpo = _corpo_da_funcao(funcao)
        assert "malhaCache.features" in corpo, (
            f"{funcao} não desenha a malha inteira"
        )
        assert "soDoEstado" not in corpo, (
            f"{funcao} voltou a recortar o desenho por estado"
        )


def test_a_camera_move_as_tres_camadas_juntas():
    """
    Mapa, chuva e capitais têm de sair de registro nunca. Ficando todas dentro
    do mesmo elemento transformado, uma só matriz move as três — qualquer uma
    delas fora da câmera ficaria parada enquanto as outras voam.
    """
    html = _html()
    for mapa in ("mapa", "ano"):
        camera = html[html.index(f'id="camera-{mapa}"'):]
        camera = camera[:camera.index("</div>")]
        for camada in (f'id="{mapa}-svg"', f'id="{mapa}-chuva-canvas"',
                       f'id="{mapa}-capitais-svg"'):
            assert camada in camera, f"{camada} está fora da câmera"


def test_a_espessura_do_traco_e_dividida_pelo_zoom():
    """
    `vector-effect: non-scaling-stroke` só compensa transformações de dentro do
    SVG, e o zoom da câmera é um `transform` CSS num elemento acima dele. Sem
    dividir a espessura pela escala, o traço de 2px do município em foco vira
    uma faixa de cinquenta pixels no fim do voo.
    """
    css, js = _css(), _js()
    assert "calc(2.2 / var(--zoom))" in css, (
        "o contorno de foco não corrige a espessura pelo zoom"
    )
    assert 'setProperty("--zoom"' in js, (
        "o app.js não publica a escala corrente da câmera"
    )


def test_o_voo_termina_mesmo_sem_quadros():
    """
    Em aba escondida o navegador não entrega quadro nenhum. Um voo que
    esperasse por eles nunca terminaria, e a previsão inteira ficaria pendurada
    em "Calculando..." até alguém voltar para a aba.
    """
    js = _js()
    assert "document.hidden" in _corpo_da_funcao("function voar("), (
        "voar() não trata a página escondida"
    )
    assert "visibilitychange" in js, (
        "nada conclui um voo que já estava em curso quando a aba sumiu"
    )


def test_o_cenario_carrega_antes_do_app():
    """
    O app.js chama Cenario.globo() e Cenario.clima() já na inicialização. Fora
    de ordem, a página abre num erro de referência e nada mais acontece.
    """
    html = _html()
    assert html.index('src="cenario.js"') < html.index('src="app.js"')


def test_o_fundo_animado_para_quando_sai_de_cena():
    """
    Dois cenários desenhando ao mesmo tempo é o dobro do custo para mostrar
    metade — um deles está sempre atrás de um palco invisível.
    """
    corpo = _corpo_da_funcao("function trocarPalco(")
    assert "pausar()" in corpo and "seguir()" in corpo
