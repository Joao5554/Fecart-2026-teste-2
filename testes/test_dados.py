"""
Testes do ETL do Atlas e da validação do dataset.

O teste mais importante deste arquivo é o de **vazamento temporal**: ele
garante que nenhuma feature de um mês use informação daquele mês ou do
futuro. Sem essa garantia, a acurácia do projeto inteiro seria fantasia.
"""

import numpy as np
import pandas as pd
import pytest

from src import atlas, caracteristicas, esquema
from src.carregar import validar


# --------------------------------------------------------------------------
# Formato do dataset produzido pelo ETL
# --------------------------------------------------------------------------


def test_dataset_segue_o_contrato(dados_exemplo):
    for coluna in esquema.COLUNAS_OBRIGATORIAS:
        assert coluna in dados_exemplo.columns, f"faltou a coluna '{coluna}'"


def test_dataset_passa_na_validacao(dados_exemplo):
    relatorio = validar(dados_exemplo, exigir_alvo=True)
    assert not relatorio.erros, relatorio.erros


def test_dataset_tem_as_tres_classes(dados_exemplo):
    assert set(dados_exemplo[esquema.COLUNA_ALVO].unique()) == set(esquema.CLASSES_RISCO)


def test_dataset_nao_tem_linhas_repetidas(dados_exemplo):
    assert not dados_exemplo.duplicated(subset=esquema.CHAVE_LINHA).any()


def test_derivadas_sao_todas_criadas(dados_exemplo):
    com_derivadas = caracteristicas.adicionar_derivadas(dados_exemplo)
    for coluna in esquema.COLUNAS_DERIVADAS:
        assert coluna in com_derivadas.columns
        assert com_derivadas[coluna].notna().all()


def test_etl_e_reproduzivel(ocorrencias):
    primeiro = atlas.construir_dataset(ocorrencias, 2015, 2025, 2, semente=7)
    segundo = atlas.construir_dataset(ocorrencias, 2015, 2025, 2, semente=7)
    pd.testing.assert_frame_equal(primeiro, segundo)


# --------------------------------------------------------------------------
# Vazamento temporal — o teste central do projeto
# --------------------------------------------------------------------------


def _indice(ano, mes):
    return (ano - 1900) * 12 + (mes - 1)


def test_historico_nao_usa_o_proprio_mes_nem_o_futuro(dados_exemplo, ocorrencias):
    """
    Para cada linha, o total histórico tem de bater exatamente com o número
    de ocorrências ANTERIORES àquele mês.

    Se o ETL incluísse o próprio mês, as linhas com desastre teriam um a mais
    e o modelo "adivinharia" o rótulo — parecendo ótimo e não servindo para nada.
    """
    eventos = {}
    for chave, bloco in ocorrencias.groupby(["codigo_ibge", "grupo_desastre"]):
        eventos[chave] = np.sort(_indice(bloco["ano"].to_numpy(), bloco["mes"].to_numpy()))

    for linha in dados_exemplo.itertuples():
        chave = (linha.codigo_ibge, linha.grupo_desastre)
        alvo = _indice(linha.ano, linha.mes)
        esperado = int((eventos[chave] < alvo).sum())
        assert linha.ocorrencias_total_historico == esperado, (
            f"{chave} em {linha.ano}-{linha.mes:02d}: "
            f"esperado {esperado}, veio {linha.ocorrencias_total_historico}"
        )


def test_janela_de_12_meses_conta_a_janela_certa(dados_exemplo, ocorrencias):
    eventos = {}
    for chave, bloco in ocorrencias.groupby(["codigo_ibge", "grupo_desastre"]):
        eventos[chave] = np.sort(_indice(bloco["ano"].to_numpy(), bloco["mes"].to_numpy()))

    for linha in dados_exemplo.head(400).itertuples():
        serie = eventos[(linha.codigo_ibge, linha.grupo_desastre)]
        alvo = _indice(linha.ano, linha.mes)
        esperado = int(((serie >= alvo - 12) & (serie < alvo)).sum())
        assert linha.ocorrencias_12m == esperado


def test_meses_desde_ultima_e_sempre_positivo_ou_menos_um(dados_exemplo):
    valores = dados_exemplo["meses_desde_ultima_ocorrencia"]
    assert ((valores == -1) | (valores > 0)).all(), (
        "valor 0 significaria contar uma ocorrência do próprio mês-alvo"
    )


def test_taxa_de_positivos_varia_entre_municipios(ocorrencias):
    """
    Município que sofre muito precisa ter proporção de meses de risco MAIOR
    que um município tranquilo.

    Na primeira versão do ETL os negativos eram sorteados com cota por par
    (3 para cada positivo daquele par), o que travava a taxa de positivos em
    exatamente 25% para todo mundo. O modelo ficava incapaz de aprender que
    uns lugares são mais perigosos que outros, e nenhuma métrica de acurácia
    denunciava isso — só a análise de odds ratio revelou.
    """
    dados = atlas.construir_dataset(ocorrencias, 2015, 2025, 3, semente=7)
    dados["positivo"] = (dados[esquema.COLUNA_ALVO] != "baixo").astype(int)

    taxa = dados.groupby(["codigo_ibge", "grupo_desastre"])["positivo"].mean()

    assert taxa.std() > 0.05, (
        "a taxa de positivos é praticamente igual em todos os pares "
        f"(desvio {taxa.std():.4f}). Os negativos voltaram a ser sorteados "
        "com cota por par?"
    )


def test_par_mais_ativo_tem_taxa_maior_que_o_menos_ativo(ocorrencias):
    """A ordem tem de bater com a realidade, não só variar."""
    dados = atlas.construir_dataset(ocorrencias, 2015, 2025, 3, semente=7)
    dados["positivo"] = (dados[esquema.COLUNA_ALVO] != "baixo").astype(int)

    resumo = dados.groupby(["codigo_ibge", "grupo_desastre"]).agg(
        taxa=("positivo", "mean"), eventos=("positivo", "sum")
    )
    mais_ativo = resumo["eventos"].idxmax()
    menos_ativo = resumo["eventos"].idxmin()

    assert resumo.loc[mais_ativo, "taxa"] > resumo.loc[menos_ativo, "taxa"]


def test_sem_historico_marca_ja_ocorreu_como_zero(dados_exemplo):
    nunca = dados_exemplo[dados_exemplo["ocorrencias_total_historico"] == 0]
    if len(nunca):
        assert (nunca["ja_ocorreu"] == 0).all()
        assert (nunca["meses_desde_ultima_ocorrencia"] == -1).all()


# --------------------------------------------------------------------------
# Regra do rótulo
# --------------------------------------------------------------------------


def test_ocorrencia_com_mortos_vira_risco_alto(ocorrencias):
    dados = atlas.construir_dataset(ocorrencias, 2015, 2025, 1, semente=7)
    petropolis = dados[
        (dados["codigo_ibge"] == 3303906)
        & (dados["grupo_desastre"] == "DESLIZAMENTO")
        & (dados["mes"] == 2)
    ]
    assert len(petropolis) > 0
    assert (petropolis[esquema.COLUNA_ALVO] == "alto").all()


def test_mes_sem_ocorrencia_vira_risco_baixo(dados_exemplo, ocorrencias):
    combinacoes = {
        (linha.codigo_ibge, linha.grupo_desastre, linha.ano, linha.mes)
        for linha in ocorrencias.itertuples()
    }
    baixos = dados_exemplo[dados_exemplo[esquema.COLUNA_ALVO] == "baixo"]
    for linha in baixos.head(300).itertuples():
        chave = (linha.codigo_ibge, linha.grupo_desastre, linha.ano, linha.mes)
        assert chave not in combinacoes


def test_classificar_risco_segue_o_criterio():
    assert atlas.classificar_risco(reconhecido=True, mortos=0) == "alto"
    assert atlas.classificar_risco(reconhecido=False, mortos=2) == "alto"
    assert atlas.classificar_risco(reconhecido=False, mortos=0) == "medio"


# --------------------------------------------------------------------------
# Mapeamento das tipologias do Atlas
# --------------------------------------------------------------------------


def test_todo_grupo_mapeado_existe_no_esquema():
    for grupo in set(atlas.TIPOLOGIA_PARA_GRUPO.values()):
        assert grupo in esquema.GRUPOS_COBRADE


def test_tipologias_descartadas_nao_estao_no_mapa():
    for tipologia in atlas.TIPOLOGIAS_DESCARTADAS:
        assert tipologia not in atlas.TIPOLOGIA_PARA_GRUPO


def test_arquivo_bruto_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(atlas.ErroAtlas, match="não encontrado"):
        atlas.carregar_atlas(tmp_path / "nao_existe.csv")


def test_periodo_sem_ocorrencias_da_erro_claro(ocorrencias):
    with pytest.raises(atlas.ErroAtlas, match="Nenhuma ocorrência"):
        atlas.construir_dataset(ocorrencias, 1800, 1801)


# --------------------------------------------------------------------------
# Features derivadas
# --------------------------------------------------------------------------


def test_mes_ciclico_aproxima_dezembro_de_janeiro():
    base = pd.DataFrame({
        "mes": [12, 1, 6],
        "anos_de_historico": [1.0, 1.0, 1.0],
        "ocorrencias_total_historico": [1.0, 1.0, 1.0],
        "reconhecimentos_historico": [0.0, 0.0, 0.0],
        "afetados_historico": [0.0, 0.0, 0.0],
    })
    d = caracteristicas.adicionar_derivadas(base)

    def distancia(i, j):
        return np.hypot(
            d["mes_seno"][i] - d["mes_seno"][j],
            d["mes_cosseno"][i] - d["mes_cosseno"][j],
        )

    assert distancia(0, 1) < distancia(0, 2)


def test_derivadas_nao_estouram_com_historico_zerado():
    base = pd.DataFrame({
        "mes": [5],
        "anos_de_historico": [0.0],
        "ocorrencias_total_historico": [0.0],
        "reconhecimentos_historico": [0.0],
        "afetados_historico": [0.0],
    })
    d = caracteristicas.adicionar_derivadas(base)
    assert d["ocorrencias_por_ano"].iloc[0] == 0.0
    assert d["proporcao_reconhecidas"].iloc[0] == 0.0
    assert d["gravidade_media_historica"].iloc[0] == 0.0
    assert np.isfinite(d[esquema.COLUNAS_DERIVADAS].to_numpy()).all()


def test_proporcao_reconhecidas_fica_entre_zero_e_um(dados_exemplo):
    d = caracteristicas.adicionar_derivadas(dados_exemplo)
    assert d["proporcao_reconhecidas"].between(0, 1).all()


# --------------------------------------------------------------------------
# Validação do CSV
# --------------------------------------------------------------------------


def test_validacao_acusa_coluna_faltando(dados_exemplo):
    incompleto = dados_exemplo.drop(columns=["ocorrencias_12m"])
    relatorio = validar(incompleto, exigir_alvo=True)
    assert any("ocorrencias_12m" in erro for erro in relatorio.erros)


def test_validacao_acusa_nivel_de_risco_invalido(dados_exemplo):
    quebrado = dados_exemplo.copy()
    quebrado.loc[quebrado.index[0], esquema.COLUNA_ALVO] = "altissimo"
    relatorio = validar(quebrado, exigir_alvo=True)
    assert relatorio.erros


def test_validacao_avisa_uf_desconhecida(dados_exemplo):
    quebrado = dados_exemplo.copy()
    quebrado.loc[quebrado.index[0], "uf"] = "ZZ"
    relatorio = validar(quebrado, exigir_alvo=True)
    assert any("uf" in aviso for aviso in relatorio.avisos)
