"""
Testes da ferramenta que empacota o projeto para apresentar em outro
computador.

O risco aqui é silencioso: a ferramenta lista quais pastas e arquivos copiar,
e se alguém renomear algo no projeto sem atualizar essa lista, o pacote sai
incompleto — e isso só apareceria na hora da apresentação.
"""

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FERRAMENTA = RAIZ / "ferramentas" / "preparar_apresentacao.py"

pytestmark = pytest.mark.skipif(
    not FERRAMENTA.exists(), reason="ferramenta de empacotamento não encontrada"
)


def _modulo():
    especificacao = importlib.util.spec_from_file_location(
        "preparar_apresentacao", FERRAMENTA
    )
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def test_pastas_listadas_existem_no_projeto():
    for pasta in _modulo().PASTAS_CODIGO:
        assert (RAIZ / pasta).is_dir(), (
            f"a ferramenta copia '{pasta}/', que não existe mais no projeto"
        )


def test_arquivos_de_codigo_listados_existem():
    for arquivo in _modulo().ARQUIVOS_CODIGO:
        assert (RAIZ / arquivo).is_file(), (
            f"a ferramenta copia '{arquivo}', que não existe mais"
        )


def test_pacote_inclui_o_que_a_api_precisa_em_execucao():
    """
    O pacote tem de levar o modelo e o histórico — e nada além do necessário.

    Sem o modelo a API não prevê; sem ocorrencias.csv a consulta por município
    não funciona. Já o dados.csv (24 MB) só serve para treinar e fica de fora
    de propósito.
    """
    from backend import app as backend_app

    caminhos = {caminho for caminho, _ in _modulo().ARQUIVOS_GERADOS}

    assert "modelo/modelo.pkl" in caminhos
    assert "dados/ocorrencias.csv" in caminhos
    assert "dados/dados.csv" not in caminhos

    # Os caminhos declarados precisam bater com os que o backend carrega.
    assert backend_app.ARQUIVO_MODELO.name == "modelo.pkl"
    assert backend_app.ARQUIVO_OCORRENCIAS.name == "ocorrencias.csv"


def test_leiame_e_formatavel():
    """O texto usa {instrucao_instalacao}; qualquer chave a mais quebraria."""
    texto = _modulo().LEIAME.format(instrucao_instalacao="pip install")
    assert "pip install" in texto
    assert "{" not in texto.replace("{{", "").replace("}}", "")


def test_leiame_aponta_o_endereco_certo_da_interface():
    texto = _modulo().LEIAME.format(instrucao_instalacao="")
    assert "127.0.0.1:8000/app" in texto


def test_remover_pasta_apaga_de_verdade(tmp_path):
    alvo = tmp_path / "pacote"
    (alvo / "sub").mkdir(parents=True)
    (alvo / "sub" / "arquivo.txt").write_text("x", encoding="utf-8")

    _modulo().remover_pasta(alvo)
    assert not alvo.exists()


def test_remover_pasta_vence_arquivo_somente_leitura(tmp_path):
    """
    Arquivo somente-leitura faz o rmtree padrão falhar no Windows.

    Acontece de verdade com pastas dentro do OneDrive, que é onde este
    projeto costuma ficar.
    """
    import os
    import stat

    alvo = tmp_path / "pacote"
    alvo.mkdir()
    arquivo = alvo / "travado.txt"
    arquivo.write_text("x", encoding="utf-8")
    os.chmod(arquivo, stat.S_IREAD)

    _modulo().remover_pasta(alvo)
    assert not alvo.exists()
