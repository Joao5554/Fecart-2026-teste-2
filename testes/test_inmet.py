"""
Testes do leitor de dados do INMET.

Estes testes fabricam arquivos no formato exato do INMET, incluindo as
variações que o instituto usou ao longo dos anos: nomes de coluna diferentes,
formatos de data diferentes e o código -9999 para valor faltante.

Isso importa porque o projeto vai ler de uma vez arquivos de 2010 a 2025, e
um parser que só entenda o formato de um ano falharia na metade da base.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import inmet

# Cabeçalho de 8 linhas, igual ao dos arquivos reais.
CABECALHO = """REGIAO:;SE
UF:;RJ
ESTACAO:;PETROPOLIS
CODIGO (WMO):;A610
LATITUDE:;-22,50472222
LONGITUDE:;-43,17805555
ALTITUDE:;800,00
DATA DE FUNDACAO:;01/01/07"""

# Grafia usada nos arquivos mais antigos.
COLUNAS_ANTIGAS = (
    "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);"
    "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);"
    "UMIDADE RELATIVA DO AR, HORARIA (%);VENTO, RAJADA MAXIMA (m/s);"
)

# Grafia usada nos arquivos recentes: nomes e formato de data mudaram.
COLUNAS_NOVAS = (
    "DATA (YYYY-MM-DD);HORA (UTC);PRECIPITACAO TOTAL, HORARIO (mm);"
    "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);"
    "UMIDADE RELATIVA DO AR, HORARIA (%);VENTO, RAJADA MAXIMA (m/s);"
)


def escrever_estacao(caminho: Path, ano: int, formato: str = "antigo",
                     chuva_por_hora: float = 0.5, horas_faltando: int = 0,
                     estacao: str = "PETROPOLIS", uf: str = "RJ") -> Path:
    """
    Gera um CSV de estação no formato do INMET.

    Cria 3 dias de janeiro, com 24 registros horários cada.
    """
    cabecalho = CABECALHO.replace("PETROPOLIS", estacao).replace("UF:;RJ", f"UF:;{uf}")
    colunas = COLUNAS_ANTIGAS if formato == "antigo" else COLUNAS_NOVAS

    linhas = [cabecalho, colunas]
    contador = 0

    for dia in (1, 2, 3):
        for hora in range(24):
            data = (f"{ano}/01/{dia:02d}" if formato == "antigo"
                    else f"{ano}-01-{dia:02d}")
            contador += 1

            if contador <= horas_faltando:
                # -9999 é como o INMET marca ausência de medição.
                valores = "-9999;-9999;-9999;-9999"
            else:
                valores = (f"{chuva_por_hora:.1f}".replace(".", ",")
                           + ";25,0;80,0;10,0")

            linhas.append(f"{data};{hora:02d}00 UTC;{valores};")

    caminho.write_text("\n".join(linhas), encoding="latin-1")
    return caminho


# --------------------------------------------------------------------------
# Metadados
# --------------------------------------------------------------------------


def test_le_o_cabecalho_da_estacao(tmp_path):
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2015)
    metadados, _ = inmet.ler_estacao(arquivo)

    assert metadados["estacao"] == "PETROPOLIS"
    assert metadados["uf"] == "RJ"
    assert metadados["codigo"] == "A610"
    assert metadados["latitude"] == pytest.approx(-22.5047, abs=1e-3)
    assert metadados["longitude"] == pytest.approx(-43.1780, abs=1e-3)
    assert metadados["altitude"] == pytest.approx(800.0)


def test_cabecalho_com_acentuacao_corrompida(tmp_path):
    """
    Nos arquivos de 2019 o próprio INMET gravou 'REGI?O' e 'ESTAC?O', com a
    acentuação quebrada na origem. O leitor precisa entender assim mesmo.
    """
    cabecalho_quebrado = (CABECALHO
                          .replace("REGIAO:", "REGI?O:")
                          .replace("ESTACAO:", "ESTAC?O:")
                          .replace("DATA DE FUNDACAO:", "DATA DE FUNDAC?O:"))
    arquivo = tmp_path / "2019.CSV"
    arquivo.write_text(
        "\n".join([cabecalho_quebrado, COLUNAS_ANTIGAS,
                   "2019/01/01;0000 UTC;1,0;25,0;80,0;10,0;"]),
        encoding="latin-1",
    )

    metadados, medicoes = inmet.ler_estacao(arquivo)

    assert metadados["estacao"] == "PETROPOLIS"
    assert metadados["uf"] == "RJ"
    assert metadados["latitude"] == pytest.approx(-22.5047, abs=1e-3)
    assert len(medicoes) == 1


def test_cabecalho_sem_estacao_da_erro_claro(tmp_path):
    arquivo = tmp_path / "ruim.CSV"
    arquivo.write_text("qualquer coisa\n" * 10, encoding="latin-1")

    with pytest.raises(inmet.ErroInmet, match="estacao|Cabeçalho"):
        inmet.ler_estacao(arquivo)


# --------------------------------------------------------------------------
# Tolerância aos formatos que mudaram entre anos
# --------------------------------------------------------------------------


@pytest.mark.parametrize("formato", ["antigo", "novo"])
def test_le_as_duas_grafias_de_coluna(tmp_path, formato):
    """
    O teste central: o INMET mudou os nomes das colunas e o formato da data.
    Um parser que dependesse do nome exato leria só metade da base.
    """
    arquivo = escrever_estacao(tmp_path / f"{formato}.CSV", 2020, formato=formato)
    _, medicoes = inmet.ler_estacao(arquivo)

    assert len(medicoes) == 72
    assert medicoes["data"].dt.year.unique().tolist() == [2020]
    assert medicoes["precipitacao"].notna().all()
    assert medicoes["temperatura"].iloc[0] == pytest.approx(25.0)
    assert medicoes["umidade"].iloc[0] == pytest.approx(80.0)


def test_valor_faltante_vira_nulo(tmp_path):
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2018, horas_faltando=24)
    _, medicoes = inmet.ler_estacao(arquivo)

    assert medicoes["precipitacao"].isna().sum() == 24
    assert not (medicoes["precipitacao"] < 0).any(), "-9999 virou chuva negativa"


def test_arquivo_em_utf8_tambem_e_lido(tmp_path):
    """Nem todo arquivo baixado está em latin-1; alguns vêm reconvertidos."""
    arquivo = tmp_path / "utf8.CSV"
    conteudo = "\n".join([CABECALHO, COLUNAS_ANTIGAS,
                          "2019/01/01;0000 UTC;1,0;25,0;80,0;10,0;"])
    arquivo.write_text(conteudo, encoding="utf-8")

    metadados, medicoes = inmet.ler_estacao(arquivo)
    assert metadados["uf"] == "RJ"
    assert len(medicoes) == 1


# --------------------------------------------------------------------------
# Agregação mensal
# --------------------------------------------------------------------------


def test_soma_a_chuva_do_mes(tmp_path):
    # 72 horas com 0,5 mm cada = 36 mm no mês.
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2015, chuva_por_hora=0.5)
    metadados, medicoes = inmet.ler_estacao(arquivo)
    mensal = inmet.agregar_mensal(medicoes, metadados)

    assert len(mensal) == 1
    assert mensal["chuva_total_mm"].iloc[0] == pytest.approx(36.0)


def test_chuva_maxima_em_um_dia(tmp_path):
    """24 horas de 0,5 mm dão 12 mm por dia."""
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2015, chuva_por_hora=0.5)
    metadados, medicoes = inmet.ler_estacao(arquivo)
    mensal = inmet.agregar_mensal(medicoes, metadados)

    assert mensal["chuva_max_dia_mm"].iloc[0] == pytest.approx(12.0)
    assert mensal["dias_com_chuva"].iloc[0] == 3


def test_dias_sem_chuva_nao_sao_contados(tmp_path):
    arquivo = escrever_estacao(tmp_path / "seco.CSV", 2015, chuva_por_hora=0.0)
    metadados, medicoes = inmet.ler_estacao(arquivo)
    mensal = inmet.agregar_mensal(medicoes, metadados)

    assert mensal["chuva_total_mm"].iloc[0] == 0.0
    assert mensal["dias_com_chuva"].iloc[0] == 0


def test_rajada_convertida_para_km_por_hora(tmp_path):
    """O INMET grava em m/s; 10 m/s são 36 km/h."""
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2015)
    metadados, medicoes = inmet.ler_estacao(arquivo)
    mensal = inmet.agregar_mensal(medicoes, metadados)

    assert mensal["rajada_max_kmh"].iloc[0] == pytest.approx(36.0)


def test_fracao_valida_reflete_as_horas_faltando(tmp_path):
    arquivo = escrever_estacao(tmp_path / "e.CSV", 2015, horas_faltando=36)
    metadados, medicoes = inmet.ler_estacao(arquivo)
    mensal = inmet.agregar_mensal(medicoes, metadados)

    assert mensal["fracao_valida"].iloc[0] == pytest.approx(0.5, abs=0.01)


# --------------------------------------------------------------------------
# Leitura de uma pasta inteira
# --------------------------------------------------------------------------


def test_le_varias_estacoes_e_varios_anos(tmp_path):
    (tmp_path / "2015").mkdir()
    (tmp_path / "2020").mkdir()
    escrever_estacao(tmp_path / "2015" / "a.CSV", 2015, formato="antigo")
    escrever_estacao(tmp_path / "2020" / "b.CSV", 2020, formato="novo",
                     estacao="QUIXADA", uf="CE")

    mensal = inmet.carregar_pasta(tmp_path)

    assert len(mensal) == 2
    assert set(mensal["estacao"]) == {"PETROPOLIS", "QUIXADA"}
    assert set(mensal["ano"]) == {2015, 2020}


def test_arquivo_corrompido_nao_derruba_a_leitura(tmp_path):
    """Um ZIP do INMET quase sempre tem alguma estação com arquivo ruim."""
    escrever_estacao(tmp_path / "boa.CSV", 2015)
    (tmp_path / "ruim.CSV").write_text("lixo\n" * 3, encoding="latin-1")

    mensal = inmet.carregar_pasta(tmp_path)

    assert len(mensal) == 1
    assert len(mensal.attrs["arquivos_com_falha"]) == 1


def test_mes_muito_incompleto_e_descartado(tmp_path):
    # 60 das 72 horas faltando: fração válida de 0,17.
    escrever_estacao(tmp_path / "furada.CSV", 2015, horas_faltando=60)
    mensal = inmet.carregar_pasta(tmp_path, minimo_valido=0.5)

    assert len(mensal) == 0
    assert mensal.attrs["meses_descartados"] == 1


def test_pasta_vazia_da_instrucao_de_download(tmp_path):
    with pytest.raises(inmet.ErroInmet, match="portal.inmet.gov.br"):
        inmet.carregar_pasta(tmp_path)


# --------------------------------------------------------------------------
# Normal climatológica
# --------------------------------------------------------------------------


def _mensal_sintetico(anos, chuva_por_ano):
    return pd.DataFrame([
        {"estacao": "PETROPOLIS", "uf": "RJ", "ano": ano, "mes": 1,
         "chuva_total_mm": chuva_por_ano[ano]}
        for ano in anos
    ])


def test_normal_usa_so_o_periodo_de_referencia():
    """
    A normal precisa vir de anos anteriores ao estudo. Se incluísse 2010–2025,
    a média carregaria informação dos anos que o modelo vai prever.
    """
    chuvas = {2005: 100.0, 2008: 200.0, 2015: 900.0, 2020: 900.0}
    mensal = _mensal_sintetico(chuvas, chuvas)

    normais = inmet.calcular_normais(mensal, ano_inicial=2000, ano_final=2009)

    assert len(normais) == 1
    assert normais["chuva_normal_mm"].iloc[0] == pytest.approx(150.0)
    assert normais["anos_na_normal"].iloc[0] == 2


def test_normal_vazia_quando_nao_ha_periodo_de_referencia():
    chuvas = {2015: 100.0, 2020: 200.0}
    normais = inmet.calcular_normais(_mensal_sintetico(chuvas, chuvas),
                                     ano_inicial=2000, ano_final=2009)
    assert normais.empty
