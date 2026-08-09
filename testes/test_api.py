"""
Testes da API.

Precisam do modelo já treinado (modelos/modelo.pkl). Se ele não existir,
os testes são pulados com uma mensagem explicando o que fazer.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from treinamento.esquema import ARQUIVO_MODELO, CLASSES, exemplo_entrada

pytestmark = pytest.mark.skipif(
    not ARQUIVO_MODELO.exists(),
    reason="Modelo não treinado. Rode: python treinamento/treinar_modelo.py",
)

cliente = TestClient(app)


def test_raiz_responde():
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert resposta.json()["modelo_carregado"] is True


def test_saude():
    assert cliente.get("/saude").status_code == 200


def test_info_do_modelo():
    dados = cliente.get("/modelo/info").json()
    assert dados["modelo_carregado"] is True
    assert dados["versao_modelo"]
    assert set(dados["classes"]) == set(CLASSES)
    assert "f1_macro" in dados["metricas"]


def test_info_avisa_quando_os_dados_sao_sinteticos():
    dados = cliente.get("/modelo/info").json()
    if dados["origem_dados"] == "sintetico":
        assert "SINTÉTICOS" in dados["aviso"]


def test_opcoes_lista_os_campos():
    dados = cliente.get("/opcoes").json()
    nomes = {campo["nome"] for campo in dados["campos"]}
    assert "precipitacao_mm" in nomes
    assert "SP" in next(c for c in dados["campos"] if c["nome"] == "uf")["categorias"]


def test_previsao_simples():
    resposta = cliente.post("/prever", json=exemplo_entrada())
    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["tipo_desastre_previsto"] in CLASSES
    assert 0.0 <= dados["confianca"] <= 1.0
    assert dados["nivel_risco"] in {"baixo", "moderado", "alto", "muito_alto"}
    assert abs(sum(dados["probabilidades"].values()) - 1.0) < 0.01


def test_cenario_de_muita_chuva_em_encosta_aumenta_o_risco():
    """Teste de comportamento: condição extrema precisa elevar o risco."""
    calmo = exemplo_entrada() | {
        "precipitacao_mm": 20.0,
        "precipitacao_max_24h_mm": 5.0,
        "declividade_media_pct": 2.0,
        "rajada_vento_max_kmh": 10.0,
    }
    extremo = exemplo_entrada() | {
        "precipitacao_mm": 620.0,
        "precipitacao_max_24h_mm": 190.0,
        "declividade_media_pct": 38.0,
        "dias_com_chuva": 26,
    }

    risco_calmo = cliente.post("/prever", json=calmo).json()[
        "probabilidade_algum_desastre"
    ]
    risco_extremo = cliente.post("/prever", json=extremo).json()[
        "probabilidade_algum_desastre"
    ]
    assert risco_extremo > risco_calmo


def test_previsao_em_lote():
    lote = [exemplo_entrada() | {"mes": mes} for mes in range(1, 13)]
    resposta = cliente.post("/prever-lote", json=lote)
    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["total"] == 12
    assert len(dados["previsoes"]) == 12


def test_lote_vazio_e_recusado():
    assert cliente.post("/prever-lote", json=[]).status_code == 400


def test_campo_faltando_e_recusado():
    entrada = exemplo_entrada()
    del entrada["precipitacao_mm"]
    assert cliente.post("/prever", json=entrada).status_code == 422


def test_valor_fora_da_faixa_e_recusado():
    entrada = exemplo_entrada() | {"mes": 13}
    assert cliente.post("/prever", json=entrada).status_code == 422


def test_categoria_invalida_e_recusada():
    entrada = exemplo_entrada() | {"uf": "XX"}
    resposta = cliente.post("/prever", json=entrada)
    assert resposta.status_code == 422
    assert "inválido" in resposta.text
