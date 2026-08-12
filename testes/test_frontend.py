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
    conteudo = _js()
    inicio = conteudo.index("async function iniciar()")
    corpo = conteudo[inicio:inicio + 600]

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
