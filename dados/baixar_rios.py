"""
Baixa a rede de rios que cobre o Brasil — a geografia que não muda com o tempo.

Como executar (a partir da raiz do projeto):
    python dados/baixar_rios.py

O arquivo gerado (`dados/rios_brasil.json`, ~1 MB) VAI para o repositório: é
pequeno, não muda e serve de entrada para `dados/preparar_geografia.py`.

Por que rios
------------
Todas as variáveis do modelo saem do histórico de ocorrências, e histórico
envelhece: quem consulta um mês de 2027 recebe a fotografia de dezembro de
2025 (ver `src/atlas._ancora`). Geografia não envelhece. Um município à
margem do Amazonas continua à margem do Amazonas em qualquer ano, e essa é
exatamente a informação que falta quando o histórico congela.

De onde vem
-----------
Natural Earth, escala 1:10m — domínio público, sem restrição de uso e sem
cadastro. É a rede de rios PRINCIPAIS: Amazonas, Negro, Madeira, Tapajós,
Xingu, Tocantins, São Francisco, Paraná, Paraguai, Uruguai e afluentes
grandes. Igarapé de bairro não está aqui, e essa limitação é real — vale
para medir "beira de rio grande", não "beira d'água".

    https://www.naturalearthdata.com/downloads/10m-physical-vectors/
"""

import argparse
import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "dados" / "rios_brasil.json"

URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
       "master/geojson/ne_10m_rivers_lake_centerlines.geojson")

# O mesmo retângulo do relevo: cobre o Brasil com folga e entra um pouco nos
# vizinhos, o que é proposital — um município de fronteira pode estar mais
# perto de um trecho de rio que corre do lado de lá.
LON_OESTE, LON_LESTE = -74.5, -34.0
LAT_SUL, LAT_NORTE = -34.0, 5.5

# Três casas decimais são ~110 metros, resolução muito acima do que o resto do
# projeto usa (a grade de relevo tem 2,2 km). Corta o arquivo quase pela metade.
CASAS_DECIMAIS = 3


def baixar() -> dict:
    """
    Busca o GeoJSON.

    Usa `curl` em vez das bibliotecas do Python pelo mesmo motivo de
    `baixar_malha.py`: em rede com inspeção de certificado — comum em escola —
    o urllib falha na verificação SSL e o curl, que usa o repositório de
    certificados do sistema, funciona.
    """
    resultado = subprocess.run(
        ["curl", "-sS", "-L", "-m", "300", "--retry", "2", URL],
        capture_output=True, text=True, encoding="utf-8",
    )
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip()[:200])
    return json.loads(resultado.stdout)


def linhas_da_feicao(geometria: dict) -> list[list]:
    """Achata LineString e MultiLineString numa lista de linhas."""
    if geometria["type"] == "LineString":
        return [geometria["coordinates"]]
    if geometria["type"] == "MultiLineString":
        return list(geometria["coordinates"])
    return []


def dentro_do_retangulo(linha: list) -> bool:
    return any(
        LON_OESTE <= lon <= LON_LESTE and LAT_SUL <= lat <= LAT_NORTE
        for lon, lat, *_ in linha
    )


def recortar(linha: list) -> list:
    """Mantém só os vértices dentro do retângulo, arredondados."""
    return [
        [round(lon, CASAS_DECIMAIS), round(lat, CASAS_DECIMAIS)]
        for lon, lat, *_ in linha
        if LON_OESTE <= lon <= LON_LESTE and LAT_SUL <= lat <= LAT_NORTE
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()

    print("Baixando a rede de rios do Natural Earth (7 MB)...", flush=True)
    try:
        geo = baixar()
    except (RuntimeError, json.JSONDecodeError) as erro:
        print(f"Falhou: {erro}")
        return 1

    print(f"  {len(geo['features']):,} trechos no mundo inteiro.")

    trechos = []
    for feicao in geo["features"]:
        propriedades = feicao.get("properties") or {}
        # `scalerank` mede a importância do rio: quanto MENOR, mais
        # significativo. O Amazonas é 0; um afluente pequeno chega a 9. Guardar
        # isso permite depois perguntar "perto de um rio grande" em vez de
        # "perto de qualquer rio".
        ordem = propriedades.get("scalerank")
        nome = propriedades.get("name") or propriedades.get("name_en")

        for linha in linhas_da_feicao(feicao["geometry"]):
            if not dentro_do_retangulo(linha):
                continue
            recortada = recortar(linha)
            # Um vértice solto não é um trecho de rio: pode ser a ponta de um
            # rio que só encosta na borda do retângulo.
            if len(recortada) < 2:
                continue
            trechos.append({
                "nome": nome,
                "ordem": ordem,
                "pontos": recortada,
            })

    if not trechos:
        print("Nenhum trecho de rio caiu dentro do Brasil. Nada foi salvo.")
        return 1

    vertices = sum(len(t["pontos"]) for t in trechos)
    nomeados = sorted({t["nome"] for t in trechos if t["nome"]})

    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(
        json.dumps({
            "fonte": "Natural Earth 1:10m — rivers + lake centerlines",
            "url": URL,
            "retangulo": {"lon_oeste": LON_OESTE, "lon_leste": LON_LESTE,
                          "lat_sul": LAT_SUL, "lat_norte": LAT_NORTE},
            "trechos": trechos,
        }, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    tamanho = argumentos.saida.stat().st_size / 1024 / 1024
    print(f"\n{len(trechos):,} trechos e {vertices:,} vértices salvos em "
          f"{argumentos.saida.name} ({tamanho:.1f} MB)")
    print(f"{len(nomeados)} rios nomeados. Alguns: "
          + ", ".join(nomeados[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
