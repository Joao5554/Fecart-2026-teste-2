"""
Baixa a malha das 27 unidades federativas do IBGE — a fronteira dos estados.

Como executar (a partir da raiz do projeto):
    python dados/baixar_malha_estados.py

O arquivo gerado (`dados/malha_estados.json`, ~100 KB) VAI para o repositório,
como a malha municipal. Só é preciso rodar este script se o arquivo se perder
ou se o IBGE mudar a divisão política.

Por que uma malha separada
--------------------------
O mapa já tem os 5.570 municípios, e a fronteira de um estado é, em tese, a
soma das fronteiras dos municípios dele. Só que desenhar essa soma exigiria
unir os polígonos — e traçar os municípios de um estado com contorno grosso
desenha também todas as divisas internas, que é justamente o oposto do que a
camada quer mostrar.

100 KB resolvem isso sem nenhuma conta: são as mesmas fronteiras, no mesmo
nível de simplificação (`qualidade=minima`) da malha municipal, então as duas
se encaixam sem folga visível.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "dados" / "malha_estados.json"

# Sigla e nome de cada código do IBGE. A API devolve só o número em `codarea`,
# e é a sigla que o mapa usa para casar com o seletor "voar até o estado".
UFS = {
    11: ("RO", "Rondônia"), 12: ("AC", "Acre"), 13: ("AM", "Amazonas"),
    14: ("RR", "Roraima"), 15: ("PA", "Pará"), 16: ("AP", "Amapá"),
    17: ("TO", "Tocantins"), 21: ("MA", "Maranhão"), 22: ("PI", "Piauí"),
    23: ("CE", "Ceará"), 24: ("RN", "Rio Grande do Norte"),
    25: ("PB", "Paraíba"), 26: ("PE", "Pernambuco"), 27: ("AL", "Alagoas"),
    28: ("SE", "Sergipe"), 29: ("BA", "Bahia"), 31: ("MG", "Minas Gerais"),
    32: ("ES", "Espírito Santo"), 33: ("RJ", "Rio de Janeiro"),
    35: ("SP", "São Paulo"), 41: ("PR", "Paraná"), 42: ("SC", "Santa Catarina"),
    43: ("RS", "Rio Grande do Sul"), 50: ("MS", "Mato Grosso do Sul"),
    51: ("MT", "Mato Grosso"), 52: ("GO", "Goiás"), 53: ("DF", "Distrito Federal"),
}

URL = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
       "?formato=application/vnd.geo+json&intrarregiao=UF&qualidade=minima")

# O mesmo arredondamento da malha municipal: 3 casas são ~110 m, menos que um
# pixel num mapa do país inteiro, e as duas malhas precisam bater casa a casa
# para não abrirem fresta uma contra a outra.
CASAS_DECIMAIS = 3


def baixar(url: str) -> dict:
    """
    Busca a malha no IBGE.

    Usa `curl` em vez das bibliotecas do Python pelo mesmo motivo de
    `baixar_malha.py`: em redes com inspeção de certificado (comum em escola e
    empresa) o urllib falha na verificação SSL, e o curl, que usa o repositório
    de certificados do sistema, funciona.
    """
    resultado = subprocess.run(
        ["curl", "-sS", "-m", "120", "--retry", "2", url],
        capture_output=True, text=True, encoding="utf-8",
    )
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip()[:120])
    return json.loads(resultado.stdout)


def arredondar(valor):
    if isinstance(valor, list):
        return [arredondar(item) for item in valor]
    return round(valor, CASAS_DECIMAIS)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Baixa a malha dos estados (UF) do IBGE.")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()

    try:
        geo = baixar(URL)
    except (RuntimeError, json.JSONDecodeError) as erro:
        print(f"Falhou ao baixar a malha dos estados: {erro}", file=sys.stderr)
        return 1

    feicoes = geo.get("features", [])
    if len(feicoes) != 27:
        print(f"[aviso] vieram {len(feicoes)} estados, esperava 27.",
              file=sys.stderr)

    for feicao in feicoes:
        codigo = int(feicao["properties"]["codarea"])
        sigla, nome = UFS.get(codigo, ("??", "?"))
        feicao["properties"] = {"codigo_uf": codigo, "sigla": sigla, "nome": nome}
        feicao["geometry"]["coordinates"] = arredondar(
            feicao["geometry"]["coordinates"]
        )

    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(
        json.dumps({"type": "FeatureCollection", "features": feicoes},
                   separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )

    tamanho = argumentos.saida.stat().st_size / 1024
    print(f"{len(feicoes)} estados salvos em {argumentos.saida.name} "
          f"({tamanho:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
