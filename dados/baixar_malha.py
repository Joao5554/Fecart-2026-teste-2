"""
Baixa a malha municipal do IBGE — as fronteiras que o mapa desenha.

Como executar (a partir da raiz do projeto):
    python dados/baixar_malha.py

O arquivo gerado (`dados/malha_municipios.json`, ~3 MB) VAI para o
repositório, para que o mapa funcione logo depois de um `git clone`. Só é
preciso rodar este script se o arquivo se perder ou se o IBGE atualizar a
divisão municipal.

Por que qualidade "mínima"
--------------------------
O IBGE oferece as fronteiras em várias resoluções. A máxima passa de 100 MB e
travaria o navegador ao desenhar 5.570 polígonos. A mínima ocupa 3 MB e, num
mapa do país inteiro, tem exatamente a mesma aparência — cada município ocupa
poucos pixels na tela.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "dados" / "malha_municipios.json"

# Códigos das 27 unidades federativas no IBGE.
UFS = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL",
    28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
    42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}

URL = ("https://servicodados.ibge.gov.br/api/v3/malhas/estados/{}"
       "?formato=application/vnd.geo+json&intrarregiao=municipio"
       "&qualidade=minima")

# Três casas decimais equivalem a ~110 metros. Num mapa do Brasil inteiro isso
# é bem menos que um pixel, e corta o arquivo quase pela metade.
CASAS_DECIMAIS = 3


def baixar(codigo: int) -> dict:
    """
    Busca a malha de um estado.

    Usa `curl` em vez das bibliotecas do Python de propósito: em redes com
    inspeção de certificado (comum em escola e empresa), o urllib falha na
    verificação SSL enquanto o curl, que usa o repositório de certificados do
    sistema, funciona.
    """
    resultado = subprocess.run(
        ["curl", "-sS", "-m", "120", "--retry", "2", URL.format(codigo)],
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
    parser = argparse.ArgumentParser(description="Baixa a malha municipal do IBGE.")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()

    feicoes, falhas = [], []

    for codigo, sigla in UFS.items():
        try:
            geo = baixar(codigo)
            feicoes.extend(geo["features"])
            print(f"  {sigla}: {len(geo['features'])} municípios", flush=True)
        except (RuntimeError, json.JSONDecodeError, KeyError) as erro:
            falhas.append((sigla, str(erro)[:80]))
            print(f"  {sigla}: FALHOU — {erro}", file=sys.stderr, flush=True)
        time.sleep(0.2)   # cortesia com o servidor do IBGE

    if falhas:
        print(f"\n{len(falhas)} estado(s) falharam. Rode de novo para completar.",
              file=sys.stderr)
        if not feicoes:
            return 1

    # Mantém só o código IBGE nas propriedades: é a única coisa que o mapa usa
    # para casar cada polígono com a previsão de risco.
    for feicao in feicoes:
        feicao["properties"] = {
            "codigo_ibge": int(feicao["properties"]["codarea"])
        }
        feicao["geometry"]["coordinates"] = arredondar(
            feicao["geometry"]["coordinates"]
        )

    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(
        json.dumps({"type": "FeatureCollection", "features": feicoes},
                   separators=(",", ":")),
        encoding="utf-8",
    )

    tamanho = argumentos.saida.stat().st_size / 1024 / 1024
    print(f"\n{len(feicoes):,} municípios salvos em {argumentos.saida.name} "
          f"({tamanho:.1f} MB)")
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
