"""Configuração e dados compartilhados pelos testes."""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

sys.path.insert(0, str(RAIZ / "dados"))
from gerar_dados_sinteticos import gerar  # noqa: E402


@pytest.fixture(scope="session")
def dados_exemplo():
    """Um dataset pequeno e válido, gerado na hora.

    Escopo de sessão porque gerar custa alguns segundos e nenhum teste
    modifica o resultado (os que precisam alterar fazem uma cópia).
    """
    return gerar(ano_inicial=2022, ano_final=2023, semente=7)


@pytest.fixture
def linha_exemplo(dados_exemplo):
    """Uma única linha, como dicionário — base para os testes da API."""
    return dados_exemplo.iloc[0].to_dict()
