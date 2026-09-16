"""
Baixa o contorno dos países — o mundo que aparece atrás do Brasil no globo.

Como executar (a partir da raiz do projeto):
    python dados/baixar_mundo.py

O arquivo gerado (`frontend/silhueta_mundo.json`, ~60 KB) VAI para o
repositório, como a malha do IBGE: assim o globo desenha o planeta inteiro
logo depois de um `git clone`, sem precisar de rede em tempo de uso.

De onde vem
-----------
Natural Earth, 1:110m — a escala de globo terrestre, feita exatamente para
mapas em que o planeta inteiro cabe numa tela. É domínio público (CC0), então
pode ser redistribuída junto com o projeto.

Por que o Brasil fica de fora
-----------------------------
O contorno do Brasil já vem da malha municipal do IBGE, por
`dados/preparar_silhueta.py`, e é muito mais detalhado que o dos vizinhos.
Desenhar os dois empilharia traço sobre traço na mesma fronteira. Aqui o
Brasil é removido, e o globo desenha o mundo por baixo e o país por cima.
"""

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "frontend" / "silhueta_mundo.json"

# Reaproveita o Douglas-Peucker que já reduz a silhueta do Brasil: é o mesmo
# problema, na mesma unidade (graus) e para o mesmo desenho.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparar_silhueta import area, simplificar   # noqa: E402

URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
       "/master/geojson/ne_110m_admin_0_countries.geojson")

# O globo desenha o planeta com poucas centenas de pixels de raio: menos de
# 3 px por grau. Meio grau de tolerância é, ali, menos de dois pixels — e corta
# o arquivo para um décimo do tamanho original.
TOLERANCIA = 0.5

# Ilhas menores que isto (em graus quadrados) não chegam a um pixel no globo.
AREA_MINIMA = 1.2

MINIMO_DE_PONTOS = 4

# O Brasil vem do IBGE, por preparar_silhueta.py.
FORA = {"Brazil", "Antarctica"}

CASAS_DECIMAIS = 2


def baixar() -> dict:
    """
    Busca o arquivo de países.

    Usa `curl` pelo mesmo motivo que `baixar_malha.py`: em rede com inspeção
    de certificado, o urllib falha na verificação SSL e o curl não.
    """
    resultado = subprocess.run(
        ["curl", "-sS", "-m", "180", "--retry", "2", "-L", URL],
        capture_output=True, text=True, encoding="utf-8",
    )
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip()[:160])
    return json.loads(resultado.stdout)


def aneis_da_feicao(geometria: dict):
    """Só os anéis externos: buracos não mudam a silhueta de um país no globo."""
    tipo = geometria.get("type")
    if tipo == "Polygon":
        poligonos = [geometria["coordinates"]]
    elif tipo == "MultiPolygon":
        poligonos = geometria["coordinates"]
    else:
        return
    for poligono in poligonos:
        if poligono:
            yield poligono[0]


def reduzir(anel):
    """Simplifica um anel e devolve None quando ele deixa de valer o desenho."""
    if area(anel) < AREA_MINIMA:
        return None

    pontos = simplificar([tuple(p[:2]) for p in anel], TOLERANCIA)
    if len(pontos) < MINIMO_DE_PONTOS:
        return None

    # Fecha o anel: o globo preenche cada país, e polígono aberto vaza cor.
    if pontos[0] != pontos[-1]:
        pontos.append(pontos[0])

    return [[round(x, CASAS_DECIMAIS), round(y, CASAS_DECIMAIS)]
            for x, y in pontos]


def main() -> int:
    print("Baixando os contornos do Natural Earth...")
    try:
        mundo = baixar()
    except (RuntimeError, json.JSONDecodeError) as erro:
        print(f"Falhou: {erro}", file=sys.stderr)
        return 1
    print(f"  {len(mundo['features'])} países")

    print("Simplificando...")
    paises = []
    for feicao in mundo["features"]:
        propriedades = feicao.get("properties") or {}
        nome = propriedades.get("ADMIN")
        if not nome or nome in FORA:
            continue

        aneis = [reduzido for anel in aneis_da_feicao(feicao.get("geometry") or {})
                 if (reduzido := reduzir(anel))]
        if not aneis:
            continue

        paises.append({
            "nome": propriedades.get("NAME_PT") or nome,
            "sigla": propriedades.get("ISO_A3") or "",
            "continente": propriedades.get("CONTINENT") or "",
            "aneis": aneis,
        })

    # Os maiores primeiro: no globo, um país pequeno desenhado depois fica por
    # cima do vizinho grande, em vez de sumir dentro dele.
    paises.sort(key=lambda p: sum(area(a) for a in p["aneis"]), reverse=True)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        json.dump({"paises": paises}, arquivo,
                  ensure_ascii=False, separators=(",", ":"))

    pontos = sum(len(a) for p in paises for a in p["aneis"])
    tamanho = SAIDA.stat().st_size / 1024
    print(f"\nPronto: {SAIDA.relative_to(RAIZ)}")
    print(f"  {len(paises)} países, {pontos} pontos, {tamanho:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
