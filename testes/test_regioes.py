"""
Testes da ligação entre estações do INMET e municípios do IBGE.

O risco aqui é silencioso: uma estação casada com o município errado joga a
chuva de um estado em outro, e nada no treino denuncia. Por isso os testes
cobrem principalmente os casos ambíguos.
"""

import json

import pandas as pd
import pytest

from src import regioes


@pytest.fixture
def municipios():
    """Lista pequena, no formato exato da API do IBGE."""
    def registro(id_, nome, uf_sigla, uf_id, imediata, intermediaria):
        return {
            "id": id_,
            "nome": nome,
            "regiao-imediata": {
                "id": imediata,
                "regiao-intermediaria": {
                    "id": intermediaria,
                    "UF": {"id": uf_id, "sigla": uf_sigla},
                },
            },
        }

    return pd.DataFrame([
        {"codigo_ibge": r["id"], "municipio": r["nome"],
         "nome_busca": regioes.normalizar(r["nome"]),
         "uf": r["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"],
         "regiao_imediata": r["regiao-imediata"]["id"],
         "regiao_intermediaria": r["regiao-imediata"]["regiao-intermediaria"]["id"]}
        for r in [
            registro(3303906, "Petrópolis", "RJ", 33, 330007, 3303),
            registro(3304557, "Rio de Janeiro", "RJ", 33, 330001, 3301),
            registro(4316907, "Santa Maria", "RS", 43, 430009, 4302),
            registro(2611606, "Santa Maria", "PE", 26, 260005, 2601),
            registro(3550308, "São Paulo", "SP", 35, 350001, 3501),
        ]
    ])


# --------------------------------------------------------------------------
# Normalização de nomes
# --------------------------------------------------------------------------


def test_normalizar_remove_acento_e_caixa():
    assert regioes.normalizar("Petrópolis") == "petropolis"
    assert regioes.normalizar("SÃO PAULO") == "sao paulo"
    assert regioes.normalizar("Quixadá") == "quixada"


def test_normalizar_limpa_pontuacao_e_espaco_extra():
    assert regioes.normalizar("  Mogi-Guaçu  ") == "mogi gucu".replace("gucu", "guacu")
    assert regioes.normalizar("D'Oeste") == "d oeste"


def test_normalizar_iguala_grafias_do_inmet_e_do_ibge():
    """O INMET escreve em maiúscula e sem acento; o IBGE, com acento."""
    assert regioes.normalizar("PETROPOLIS") == regioes.normalizar("Petrópolis")


# --------------------------------------------------------------------------
# Casamento de estações
# --------------------------------------------------------------------------


def test_casa_estacao_pelo_nome(municipios):
    estacoes = pd.DataFrame([("PETROPOLIS", "RJ")], columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert casadas["codigo_ibge"].iloc[0] == 3303906


def test_uf_desambigua_nomes_repetidos(municipios):
    """
    Existem duas "Santa Maria" na lista, em estados diferentes. Casar só pelo
    nome jogaria a chuva do Rio Grande do Sul em Pernambuco.
    """
    estacoes = pd.DataFrame([("SANTA MARIA", "RS"), ("SANTA MARIA", "PE")],
                            columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert casadas["codigo_ibge"].tolist() == [4316907, 2611606]


def test_casa_estacao_com_complemento_no_nome(municipios):
    """Nomes como 'RIO DE JANEIRO - FORTE DE COPACABANA' precisam funcionar."""
    estacoes = pd.DataFrame(
        [("RIO DE JANEIRO - FORTE DE COPACABANA", "RJ")],
        columns=["estacao", "uf"],
    )
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert casadas["codigo_ibge"].iloc[0] == 3304557


def test_prefixo_nao_casa_palavra_cortada(municipios):
    """
    'SAO PAULOZINHO' não pode virar 'São Paulo'. O casamento por prefixo exige
    que a próxima letra seja um espaço.
    """
    estacoes = pd.DataFrame([("SAO PAULOZINHO", "SP")], columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert pd.isna(casadas["codigo_ibge"].iloc[0])


def test_estacao_sem_municipio_fica_vazia_e_nao_quebra(municipios):
    estacoes = pd.DataFrame([("LUGAR NENHUM", "RJ")], columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert pd.isna(casadas["codigo_ibge"].iloc[0])
    assert len(casadas) == 1


def test_estacao_de_uf_inexistente_nao_quebra(municipios):
    estacoes = pd.DataFrame([("PETROPOLIS", "ZZ")], columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)

    assert pd.isna(casadas["codigo_ibge"].iloc[0])


# --------------------------------------------------------------------------
# Leitura do arquivo do IBGE
# --------------------------------------------------------------------------


def test_le_o_json_do_ibge(tmp_path):
    arquivo = tmp_path / "municipios.json"
    arquivo.write_text(json.dumps([{
        "id": 3303906,
        "nome": "Petrópolis",
        "regiao-imediata": {
            "id": 330007,
            "regiao-intermediaria": {"id": 3303, "UF": {"id": 33, "sigla": "RJ"}},
        },
    }]), encoding="utf-8")

    tabela = regioes.carregar_municipios(arquivo)

    assert len(tabela) == 1
    assert tabela["uf"].iloc[0] == "RJ"
    assert tabela["regiao_imediata"].iloc[0] == 330007
    assert tabela["nome_busca"].iloc[0] == "petropolis"


def test_municipio_antigo_sem_regiao_imediata_ainda_acha_a_uf(tmp_path):
    """A divisão antiga (microrregião) serve de rede para registros legados."""
    arquivo = tmp_path / "municipios.json"
    arquivo.write_text(json.dumps([{
        "id": 5100000,
        "nome": "Lugar Antigo",
        "regiao-imediata": None,
        "microrregiao": {"mesorregiao": {"UF": {"id": 51, "sigla": "MT"}}},
    }]), encoding="utf-8")

    tabela = regioes.carregar_municipios(arquivo)
    assert tabela["uf"].iloc[0] == "MT"


def test_arquivo_ausente_da_instrucao_de_download(tmp_path):
    with pytest.raises(regioes.ErroRegioes, match="servicodados.ibge.gov.br"):
        regioes.carregar_municipios(tmp_path / "nao_existe.json")


def test_json_invalido_da_erro_claro(tmp_path):
    arquivo = tmp_path / "ruim.json"
    arquivo.write_text("{isso não é json", encoding="utf-8")

    with pytest.raises(regioes.ErroRegioes, match="JSON"):
        regioes.carregar_municipios(arquivo)


def test_resumo_de_cobertura_conta_os_niveis(municipios):
    estacoes = pd.DataFrame([("PETROPOLIS", "RJ")], columns=["estacao", "uf"])
    casadas = regioes.casar_estacoes(estacoes, municipios)
    cobertura = regioes.resumir_cobertura(casadas, municipios)

    assert cobertura["estacoes"] == 1
    assert cobertura["municipios_com_estacao_propria"] == 1
    # Petrópolis é RJ, então Rio de Janeiro também fica coberto pelo nível UF.
    assert cobertura["municipios_via_uf"] == 2
    assert cobertura["total_municipios"] == len(municipios)
