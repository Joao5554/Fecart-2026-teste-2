"""
Extrai o contorno do Brasil a partir da malha municipal do IBGE.

O globo da tela de abertura precisa desenhar o pais girando, e reprojetar os
5.570 poligonos da malha a cada quadro custaria caro demais para uma animacao.
Aqui a uniao dos municipios e reduzida, uma unica vez, a algumas centenas de
pontos - o suficiente para o Brasil ser reconhecivel num globo de poucos
pixels, e leve o bastante para caber junto com a pagina.

O metodo e por rasterizacao: cada municipio e pintado numa grade de latitude e
longitude, a uniao vira uma mascara, e o contorno dessa mascara e extraido,
suavizado e simplificado. Funciona mesmo quando as fronteiras vizinhas nao
coincidem vertice a vertice na malha simplificada do IBGE, que e onde a uniao
puramente topologica falharia.

    python dados/preparar_silhueta.py

Gera frontend/silhueta_brasil.json.
"""

import json
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
MALHA = RAIZ / "dados" / "malha_municipios.json"
SAIDA = RAIZ / "frontend" / "silhueta_brasil.json"

PASSO = 0.12           # graus por celula da grade
SUAVIZACOES = 2        # passadas de Chaikin, para tirar a escada da grade
TOLERANCIA = 0.05      # graus: simplificacao Douglas-Peucker
MINIMO_DE_PONTOS = 12  # abaixo disso e ruido de ilha, nao vale desenhar


def carregar_malha() -> dict:
    if not MALHA.exists():
        raise SystemExit(
            "Malha nao encontrada em " + str(MALHA)
            + "\nRode antes: python dados/baixar_malha.py"
        )
    with open(MALHA, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def aneis_da_malha(malha: dict):
    """Todos os aneis externos de todos os municipios, um a um."""
    for feicao in malha["features"]:
        geometria = feicao.get("geometry") or {}
        tipo = geometria.get("type")
        if tipo == "Polygon":
            poligonos = [geometria["coordinates"]]
        elif tipo == "MultiPolygon":
            poligonos = geometria["coordinates"]
        else:
            continue
        for poligono in poligonos:
            if poligono:
                yield poligono[0]   # so o anel externo: buracos nao mudam a uniao


def pintar(aneis, limites) -> np.ndarray:
    """
    Marca numa grade booleana toda celula que cai dentro de algum municipio.

    Preenchimento por varredura horizontal com regra par-impar, feito apenas
    nas linhas que o anel realmente cruza - varrer a grade inteira por
    municipio seria milhares de vezes mais caro sem mudar o resultado.
    """
    lon0, lat0, colunas, linhas = limites
    grade = np.zeros((linhas, colunas), dtype=bool)

    for anel in aneis:
        pontos = np.asarray(anel, dtype=float)
        if len(pontos) < 3:
            continue

        x = (pontos[:, 0] - lon0) / PASSO
        y = (pontos[:, 1] - lat0) / PASSO

        primeira = max(int(np.floor(y.min())), 0)
        ultima = min(int(np.ceil(y.max())), linhas - 1)

        x1, y1 = x[:-1], y[:-1]
        x2, y2 = x[1:], y[1:]

        for linha in range(primeira, ultima + 1):
            centro = linha + 0.5
            # Arestas que cruzam esta varredura (uma ponta acima, outra abaixo).
            cruza = (((y1 <= centro) & (y2 > centro))
                     | ((y2 <= centro) & (y1 > centro)))
            if not cruza.any():
                continue

            ay, by = y1[cruza], y2[cruza]
            ax, bx = x1[cruza], x2[cruza]
            corte = np.sort(ax + (centro - ay) / (by - ay) * (bx - ax))

            # Os cortes vem aos pares: entra no poligono, sai do poligono.
            for i in range(0, len(corte) - 1, 2):
                inicio = int(np.ceil(corte[i] - 0.5))
                fim = int(np.floor(corte[i + 1] - 0.5))
                if fim >= inicio:
                    grade[linha, max(inicio, 0):min(fim + 1, colunas)] = True

    return grade


def segmentos_da_borda(grade: np.ndarray):
    """
    Arestas de celula que separam o preenchido do vazio.

    Cada segmento sai orientado de modo que o interior fique sempre do mesmo
    lado; e isso que permite encadea-los em aneis fechados logo depois.
    """
    linhas, colunas = grade.shape
    cheia = np.pad(grade, 1, constant_values=False)
    segmentos = []

    for linha in range(linhas + 1):
        for coluna in range(colunas + 1):
            aqui = bool(cheia[linha + 1, coluna + 1])
            acima = bool(cheia[linha, coluna + 1])
            esquerda = bool(cheia[linha + 1, coluna])

            if aqui != acima:      # aresta horizontal
                if aqui:
                    segmentos.append(((coluna, linha), (coluna + 1, linha)))
                else:
                    segmentos.append(((coluna + 1, linha), (coluna, linha)))
            if aqui != esquerda:   # aresta vertical
                if aqui:
                    segmentos.append(((coluna, linha + 1), (coluna, linha)))
                else:
                    segmentos.append(((coluna, linha), (coluna, linha + 1)))

    return segmentos


def encadear(segmentos):
    """Junta os segmentos soltos em aneis fechados."""
    saindo = {}
    for inicio, fim in segmentos:
        saindo.setdefault(inicio, []).append(fim)

    aneis = []
    for partida in list(saindo):
        while saindo.get(partida):
            anel = [partida]
            atual = partida
            while True:
                proximos = saindo.get(atual)
                if not proximos:
                    break
                seguinte = proximos.pop()
                anel.append(seguinte)
                atual = seguinte
                if atual == partida:
                    break
            if len(anel) > MINIMO_DE_PONTOS:
                aneis.append(anel)
    return aneis


def suavizar(anel):
    """Chaikin: corta os cantos da escada deixada pela grade."""
    novo = []
    for i in range(len(anel) - 1):
        (x1, y1), (x2, y2) = anel[i], anel[i + 1]
        novo.append((x1 * 0.75 + x2 * 0.25, y1 * 0.75 + y2 * 0.25))
        novo.append((x1 * 0.25 + x2 * 0.75, y1 * 0.25 + y2 * 0.75))
    if novo:
        novo.append(novo[0])
    return novo


def simplificar(pontos, tolerancia):
    """Douglas-Peucker, iterativo para nao estourar a pilha em anel grande."""
    if len(pontos) < 3:
        return pontos

    manter = [False] * len(pontos)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pontos) - 1)]

    while pilha:
        inicio, fim = pilha.pop()
        if fim <= inicio + 1:
            continue

        (x1, y1), (x2, y2) = pontos[inicio], pontos[fim]
        dx, dy = x2 - x1, y2 - y1
        comprimento = (dx * dx + dy * dy) ** 0.5

        pior, indice = -1.0, -1
        for i in range(inicio + 1, fim):
            x, y = pontos[i]
            if comprimento == 0:
                distancia = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                distancia = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / comprimento
            if distancia > pior:
                pior, indice = distancia, i

        if pior > tolerancia:
            manter[indice] = True
            pilha.append((inicio, indice))
            pilha.append((indice, fim))

    return [p for p, fica in zip(pontos, manter) if fica]


def area(anel):
    """Area pelo teorema do cadarco - serve para ordenar e descartar ilhotas."""
    total = 0.0
    for i in range(len(anel) - 1):
        (x1, y1), (x2, y2) = anel[i], anel[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def main() -> None:
    print("Lendo a malha municipal...")
    malha = carregar_malha()
    aneis = list(aneis_da_malha(malha))
    print("  " + str(len(aneis)) + " aneis de "
          + str(len(malha["features"])) + " municipios")

    todos = np.concatenate([np.asarray(a, dtype=float) for a in aneis])
    lon0, lat0 = todos[:, 0].min() - PASSO, todos[:, 1].min() - PASSO
    lon1, lat1 = todos[:, 0].max() + PASSO, todos[:, 1].max() + PASSO
    colunas = int((lon1 - lon0) / PASSO) + 1
    linhas = int((lat1 - lat0) / PASSO) + 1
    print("  grade de " + str(colunas) + "x" + str(linhas) + " celulas")

    print("Pintando os municipios na grade...")
    grade = pintar(aneis, (lon0, lat0, colunas, linhas))
    print("  " + str(int(grade.sum())) + " celulas dentro do pais")

    print("Extraindo o contorno...")
    brutos = encadear(segmentos_da_borda(grade))
    brutos.sort(key=area, reverse=True)
    print("  " + str(len(brutos)) + " aneis fechados")

    saida = []
    for anel in brutos:
        pontos = anel
        for _ in range(SUAVIZACOES):
            pontos = suavizar(pontos)
        # Da grade de volta para graus, e so entao simplifica: a tolerancia
        # esta expressa em graus, que e a unidade em que o globo desenha.
        graus = [(lon0 + x * PASSO, lat0 + y * PASSO) for x, y in pontos]
        graus = simplificar(graus, TOLERANCIA)
        if len(graus) >= MINIMO_DE_PONTOS:
            saida.append([[round(x, 3), round(y, 3)] for x, y in graus])

    # Ilhas minusculas somem no tamanho em que o globo desenha; manter as
    # maiores basta, e cada anel a menos e peso a menos na primeira tela.
    saida = saida[:8]

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        json.dump({"aneis": saida}, arquivo, separators=(",", ":"))

    pontos = sum(len(a) for a in saida)
    tamanho = SAIDA.stat().st_size / 1024
    print("\nPronto: " + str(SAIDA.relative_to(RAIZ)))
    print("  " + str(len(saida)) + " aneis, " + str(pontos)
          + " pontos, " + format(tamanho, ".1f") + " KB")


if __name__ == "__main__":
    main()
