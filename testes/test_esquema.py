"""
Testes de integridade do esquema.

Estes testes existem para impedir o erro mais perigoso do projeto:
alguém alterar as colunas em um lugar e esquecer do outro. Se o esquema
do treinamento e o da API saírem de sincronia, o teste falha na hora.
"""

from backend.esquemas import Observacao
from treinamento.esquema import (
    CLASSES,
    COLUNAS,
    COLUNAS_CATEGORICAS,
    COLUNAS_NUMERICAS,
    DESCRICAO_CLASSES,
    NOMES_COLUNAS,
    exemplo_entrada,
)


def test_api_tem_exatamente_as_colunas_do_esquema():
    campos_api = set(Observacao.model_fields)
    assert campos_api == set(NOMES_COLUNAS), (
        "Os campos da API e as colunas do esquema divergiram. "
        "Atualize backend/esquemas.py e treinamento/esquema.py juntos."
    )


def test_colunas_nao_se_repetem():
    assert len(NOMES_COLUNAS) == len(set(NOMES_COLUNAS))


def test_numericas_e_categoricas_cobrem_todas_as_colunas():
    assert set(COLUNAS_NUMERICAS) | set(COLUNAS_CATEGORICAS) == set(NOMES_COLUNAS)
    assert not set(COLUNAS_NUMERICAS) & set(COLUNAS_CATEGORICAS)


def test_toda_classe_tem_descricao():
    assert set(CLASSES) == set(DESCRICAO_CLASSES)


def test_colunas_categoricas_tem_categorias_definidas():
    for coluna in COLUNAS:
        if coluna.tipo == "categorica":
            assert coluna.categorias, f"'{coluna.nome}' não tem categorias definidas"


def test_exemplo_do_esquema_e_aceito_pela_api():
    observacao = Observacao(**exemplo_entrada())
    assert observacao.uf in dict((c.nome, c) for c in COLUNAS)["uf"].categorias
