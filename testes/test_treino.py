"""
Testes do pipeline de treinamento.

Treinam um modelo pequeno de propósito (30 árvores, 2 anos de dados) — o que
está sendo testado é o encanamento, não a qualidade da previsão.
"""

import numpy as np
import pytest
from sklearn.model_selection import train_test_split

from src import caracteristicas, esquema
from treinamento.treinar_modelo import construir_modelo


@pytest.fixture(scope="module")
def modelo_treinado(dados_exemplo):
    X, y = caracteristicas.separar_x_y(dados_exemplo)
    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=0.25, random_state=0, stratify=y
    )
    modelo = construir_modelo(arvores=30, profundidade=12, semente=0)
    modelo.fit(X_treino, y_treino)
    return modelo, X_teste, y_teste


def test_separar_x_y_nao_vaza_o_alvo(dados_exemplo):
    """Se o alvo entrar como feature, o modelo 'acerta' 100% e não serve."""
    X, y = caracteristicas.separar_x_y(dados_exemplo)

    assert esquema.COLUNA_ALVO not in X.columns
    assert len(X) == len(y)


def test_identificacao_nao_entra_como_feature(dados_exemplo):
    """codigo_ibge e ano não devem virar variável preditiva.

    O código IBGE é um identificador arbitrário; se o modelo o usasse, estaria
    decorando municípios em vez de aprender o fenômeno.
    """
    X, _ = caracteristicas.separar_x_y(dados_exemplo)

    assert "codigo_ibge" not in X.columns
    assert "ano" not in X.columns
    assert "municipio" not in X.columns


def test_modelo_treina_e_preve_as_classes_certas(modelo_treinado):
    modelo, X_teste, _ = modelo_treinado
    previsoes = modelo.predict(X_teste)

    assert len(previsoes) == len(X_teste)
    assert set(previsoes) <= set(esquema.CLASSES_RISCO)


def test_probabilidades_somam_um(modelo_treinado):
    modelo, X_teste, _ = modelo_treinado
    probabilidades = modelo.predict_proba(X_teste)

    assert probabilidades.shape[1] == len(esquema.CLASSES_RISCO)
    assert np.allclose(probabilidades.sum(axis=1), 1.0)


def test_modelo_e_melhor_que_chute_aleatorio(modelo_treinado):
    """Baliza mínima: precisa superar o acerto de chutar sempre a classe maioria."""
    from sklearn.metrics import balanced_accuracy_score

    modelo, X_teste, y_teste = modelo_treinado
    acerto = balanced_accuracy_score(y_teste, modelo.predict(X_teste))

    # Chute aleatório entre 3 classes daria ~33% de acurácia balanceada.
    assert acerto > 0.50, f"acurácia balanceada de apenas {acerto:.1%}"


def test_pipeline_aguenta_valores_faltantes(modelo_treinado, dados_exemplo):
    """A API vai receber linhas sem umidade do solo e sem nível de rio."""
    modelo, _, _ = modelo_treinado

    com_buracos = dados_exemplo.head(20).copy()
    com_buracos["umidade_solo_percentual"] = np.nan
    com_buracos["nivel_rio_m"] = np.nan

    X = caracteristicas.preparar_para_previsao(com_buracos)
    previsoes = modelo.predict(X)

    assert len(previsoes) == 20


def test_pipeline_aguenta_categoria_desconhecida(modelo_treinado, dados_exemplo):
    """Uma UF nova não pode derrubar a API em produção."""
    modelo, _, _ = modelo_treinado

    estranho = dados_exemplo.head(5).copy()
    estranho["uf"] = "ZZ"
    estranho["bioma"] = "Bioma Inexistente"

    X = caracteristicas.preparar_para_previsao(estranho)
    previsoes = modelo.predict(X)

    assert len(previsoes) == 5


def test_importancias_somam_aproximadamente_um(modelo_treinado):
    """Agregar o one-hot de volta não pode perder nem inventar peso."""
    modelo, _, _ = modelo_treinado

    nomes = list(modelo.named_steps["preparacao"].get_feature_names_out())
    importancias = modelo.named_steps["floresta"].feature_importances_
    agregadas = caracteristicas.importancia_por_coluna_original(nomes, importancias)

    assert abs(sum(agregadas.values()) - 1.0) < 1e-6


def test_importancias_voltam_para_o_nome_original(modelo_treinado):
    """'uf_SP', 'uf_RJ'... devem virar uma única entrada 'uf'."""
    modelo, _, _ = modelo_treinado

    nomes = list(modelo.named_steps["preparacao"].get_feature_names_out())
    importancias = modelo.named_steps["floresta"].feature_importances_
    agregadas = caracteristicas.importancia_por_coluna_original(nomes, importancias)

    assert "uf" in agregadas
    assert not any(n.startswith("uf_") for n in agregadas)


def test_modelo_sobrevive_a_salvar_e_carregar(modelo_treinado, tmp_path):
    """O que o backend carrega precisa prever igual ao que foi treinado."""
    import joblib

    modelo, X_teste, _ = modelo_treinado
    caminho = tmp_path / "modelo.pkl"
    joblib.dump(modelo, caminho, compress=3)

    recarregado = joblib.load(caminho)

    np.testing.assert_array_equal(
        modelo.predict(X_teste), recarregado.predict(X_teste)
    )
