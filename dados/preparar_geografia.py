"""
Geografia de cada município: altitude, relevo, tamanho e distância do rio.

Como executar (a partir da raiz do projeto):
    python dados/preparar_geografia.py

Entradas, todas já no repositório:
    dados/malha_municipios.json   fronteiras do IBGE      (python dados/baixar_malha.py)
    dados/relevo_brasil.bin       grade de altitude       (python dados/baixar_relevo.py)
    dados/rios_brasil.json        rede de rios principais (python dados/baixar_rios.py)

Saída:
    dados/geografia_municipios.csv   uma linha por município, ~5.570 linhas

Por que isto existe
-------------------
Todas as variáveis do modelo vinham do histórico de ocorrências, e histórico
envelhece: consultar um mês de 2027 devolve a fotografia de dezembro de 2025,
porque não existe dado depois disso (ver `src/atlas._ancora`). Geografia não
envelhece. A altitude de Blumenau e a distância de Manaus até o Amazonas são
as mesmas em 2025 e em 2027.

A hipótese a testar é a que qualquer pessoa levantaria olhando o mapa: cidade
baixa, plana e à beira de rio grande alaga mais; cidade de encosta íngreme
escorrega mais. Se isso já estiver dentro do histórico — e boa parte deve
estar, porque o histórico É a consequência da geografia — o ganho será zero.
Quem responde é `experimentos/testar_geografia.py`, não o bom senso.

Aproximações assumidas, todas explícitas
----------------------------------------
- Distâncias em plano equirretangular local: erro abaixo de 0,5% nas escalas
  usadas aqui, e nenhuma decisão do projeto depende da terceira casa.
- A grade de relevo tem passo de ~2,2 km. Município pequeno pode não conter
  ponto de grade nenhum; nesse caso usa-se o ponto mais próximo do centroide.
- Distância até o rio é medida do CENTROIDE, não da fronteira. Um município
  grande atravessado por um rio na ponta aparece mais longe do que está.
- A rede de rios é a principal (Natural Earth 1:10m). Córrego local não está
  nela, então a variável mede "perto de rio grande", não "perto d'água".
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ARQUIVO_MALHA = RAIZ / "dados" / "malha_municipios.json"
ARQUIVO_RELEVO = RAIZ / "dados" / "relevo_brasil.bin"
ARQUIVO_RELEVO_META = RAIZ / "dados" / "relevo_brasil.json"
ARQUIVO_RIOS = RAIZ / "dados" / "rios_brasil.json"
SAIDA_PADRAO = RAIZ / "dados" / "geografia_municipios.csv"

# Um grau de latitude são ~110,57 km; um de longitude, 111,32 km vezes o
# cosseno da latitude (os meridianos se aproximam nos polos).
KM_POR_GRAU_LAT = 110.574
KM_POR_GRAU_LON = 111.320

# `scalerank` do Natural Earth: quanto menor, mais importante o rio. Até 4
# ficam Amazonas, São Francisco, Paraná, Madeira e companhia.
ORDEM_RIO_GRANDE = 4


def titulo(texto: str) -> None:
    print(f"\n{'=' * 70}\n{texto}\n{'=' * 70}")


# --------------------------------------------------------------------------
# Geometria dos municípios
# --------------------------------------------------------------------------


def aneis_da_feicao(geometria: dict) -> list[np.ndarray]:
    """Todos os anéis de um Polygon ou MultiPolygon, como arrays (n, 2)."""
    tipo = geometria.get("type")
    if tipo == "Polygon":
        blocos = [geometria["coordinates"]]
    elif tipo == "MultiPolygon":
        blocos = geometria["coordinates"]
    else:
        return []

    aneis = []
    for poligono in blocos:
        for anel in poligono:
            pontos = np.asarray(anel, dtype=float)
            if len(pontos) >= 3:
                aneis.append(pontos[:, :2])
    return aneis


def area_e_centroide(anel: np.ndarray, lat_referencia: float) -> tuple[float, float, float]:
    """
    Área (km²) e centroide de um anel, pela fórmula do shoelace.

    As coordenadas são convertidas para quilômetros ANTES da conta. Fazer o
    shoelace direto em graus daria uma "área em graus²", que vale coisas
    diferentes no Amazonas e no Rio Grande do Sul.
    """
    x = anel[:, 0] * KM_POR_GRAU_LON * np.cos(np.radians(lat_referencia))
    y = anel[:, 1] * KM_POR_GRAU_LAT

    cruzado = x[:-1] * y[1:] - x[1:] * y[:-1]
    area2 = cruzado.sum()
    if abs(area2) < 1e-9:
        return 0.0, float(anel[:, 0].mean()), float(anel[:, 1].mean())

    cx = ((x[:-1] + x[1:]) * cruzado).sum() / (3.0 * area2)
    cy = ((y[:-1] + y[1:]) * cruzado).sum() / (3.0 * area2)

    lon = cx / (KM_POR_GRAU_LON * np.cos(np.radians(lat_referencia)))
    lat = cy / KM_POR_GRAU_LAT
    return abs(area2) / 2.0, float(lon), float(lat)


def dentro_do_poligono(lons: np.ndarray, lats: np.ndarray,
                       anel: np.ndarray) -> np.ndarray:
    """
    Teste do raio: conta quantas vezes uma semirreta cruza a fronteira.

    Ímpar = dentro. Vetorizado sobre todos os pontos de uma vez, porque a
    versão ponto a ponto levaria minutos nos 5.570 municípios.
    """
    x1, y1 = anel[:-1, 0], anel[:-1, 1]
    x2, y2 = anel[1:, 0], anel[1:, 1]

    # (n_pontos, n_arestas)
    lons = lons[:, None]
    lats = lats[:, None]

    cruza_latitude = (y1 > lats) != (y2 > lats)
    # Onde a aresta cruza a latitude do ponto, em que longitude isso acontece.
    with np.errstate(divide="ignore", invalid="ignore"):
        lon_cruzamento = x1 + (lats - y1) * (x2 - x1) / (y2 - y1)

    cruza = cruza_latitude & (lons < lon_cruzamento)
    return cruza.sum(axis=1) % 2 == 1


# --------------------------------------------------------------------------
# Relevo
# --------------------------------------------------------------------------


class Relevo:
    """A grade de altitude, com a conversão de coordenada para índice."""

    def __init__(self, caminho_bin: Path, caminho_meta: Path):
        meta = json.loads(caminho_meta.read_text(encoding="utf-8"))
        self.largura = meta["largura"]
        self.altura = meta["altura"]
        self.passo = meta["passo_graus"]
        self.lon_oeste = meta["lon_oeste"]
        self.lat_norte = meta["lat_norte"]

        bruto = np.fromfile(caminho_bin, dtype="<i2")
        esperado = self.largura * self.altura
        if bruto.size != esperado:
            raise ValueError(
                f"{caminho_bin.name} tem {bruto.size:,} valores, e o cabeçalho "
                f"diz {esperado:,}. Rode dados/baixar_relevo.py de novo."
            )
        self.grade = bruto.reshape(self.altura, self.largura).astype(np.float32)

    def coluna(self, lon):
        return np.clip(((np.asarray(lon) - self.lon_oeste) / self.passo)
                       .astype(int), 0, self.largura - 1)

    def linha(self, lat):
        # A grade vai de norte a sul: latitude maior é linha menor.
        return np.clip(((self.lat_norte - np.asarray(lat)) / self.passo)
                       .astype(int), 0, self.altura - 1)

    def lons_das_colunas(self, c0, c1):
        return self.lon_oeste + (np.arange(c0, c1) + 0.5) * self.passo

    def lats_das_linhas(self, l0, l1):
        return self.lat_norte - (np.arange(l0, l1) + 0.5) * self.passo


def estatisticas_de_relevo(relevo: Relevo, anel: np.ndarray,
                           lon_centro: float, lat_centro: float) -> dict:
    """Altitude média, mínima, amplitude e declividade dentro do município."""
    c0, c1 = relevo.coluna(anel[:, 0].min()), relevo.coluna(anel[:, 0].max()) + 1
    l0, l1 = relevo.linha(anel[:, 1].max()), relevo.linha(anel[:, 1].min()) + 1

    recorte = relevo.grade[l0:l1, c0:c1]
    if recorte.size == 0:
        return _relevo_do_ponto(relevo, lon_centro, lat_centro)

    lons = relevo.lons_das_colunas(c0, c1)
    lats = relevo.lats_das_linhas(l0, l1)
    malha_lon, malha_lat = np.meshgrid(lons, lats)

    dentro = dentro_do_poligono(malha_lon.ravel(), malha_lat.ravel(), anel)
    alturas = recorte.ravel()[dentro]

    # Município menor que a célula da grade (2,2 km) não contém ponto nenhum.
    # Acontece com centenas deles, sobretudo no Nordeste e no Sudeste.
    if alturas.size == 0:
        return _relevo_do_ponto(relevo, lon_centro, lat_centro)

    # Declividade: diferença entre células vizinhas, em metros por quilômetro.
    # Só faz sentido se o recorte tiver mais de uma célula em cada direção.
    if recorte.shape[0] > 1 and recorte.shape[1] > 1:
        km_por_celula_lat = relevo.passo * KM_POR_GRAU_LAT
        km_por_celula_lon = (relevo.passo * KM_POR_GRAU_LON
                             * np.cos(np.radians(lat_centro)))
        dy, dx = np.gradient(recorte)
        inclinacao = np.hypot(dy / km_por_celula_lat, dx / km_por_celula_lon)
        declividade = float(inclinacao.ravel()[dentro].mean())
    else:
        declividade = 0.0

    return {
        "altitude_media_m": float(alturas.mean()),
        "altitude_minima_m": float(alturas.min()),
        "amplitude_altitude_m": float(alturas.max() - alturas.min()),
        "declividade_m_por_km": declividade,
        "celulas_de_relevo": int(alturas.size),
    }


def _relevo_do_ponto(relevo: Relevo, lon: float, lat: float) -> dict:
    """Saída para município menor que a célula da grade: usa o centroide."""
    altura = float(relevo.grade[relevo.linha(lat), relevo.coluna(lon)])
    return {
        "altitude_media_m": altura,
        "altitude_minima_m": altura,
        "amplitude_altitude_m": 0.0,
        "declividade_m_por_km": 0.0,
        "celulas_de_relevo": 0,
    }


# --------------------------------------------------------------------------
# Rios
# --------------------------------------------------------------------------


def carregar_rios(caminho: Path) -> tuple[np.ndarray, np.ndarray]:
    """Devolve (todos os vértices, vértices só dos rios grandes)."""
    dados = json.loads(caminho.read_text(encoding="utf-8"))

    todos, grandes = [], []
    for trecho in dados["trechos"]:
        pontos = np.asarray(trecho["pontos"], dtype=float)
        todos.append(pontos)
        ordem = trecho.get("ordem")
        if ordem is not None and ordem <= ORDEM_RIO_GRANDE:
            grandes.append(pontos)

    return (np.vstack(todos),
            np.vstack(grandes) if grandes else np.empty((0, 2)))


def distancia_ate_os_rios(lons: np.ndarray, lats: np.ndarray,
                          rios: np.ndarray, blocos: int = 200) -> np.ndarray:
    """
    Distância, em km, de cada município até o vértice de rio mais próximo.

    Em blocos porque a matriz cheia seria 5.570 x 29.000 — 1,3 GB de uma vez,
    sem necessidade nenhuma.

    Medir até o VÉRTICE e não até o segmento é uma aproximação: com os rios
    desenhados a cada poucos quilômetros, o erro fica bem abaixo da resolução
    do resto do projeto.
    """
    if rios.size == 0:
        return np.full(len(lons), np.nan)

    resultado = np.empty(len(lons))
    for inicio in range(0, len(lons), blocos):
        fim = min(inicio + blocos, len(lons))
        lon = lons[inicio:fim, None]
        lat = lats[inicio:fim, None]

        dx = (rios[None, :, 0] - lon) * KM_POR_GRAU_LON * np.cos(np.radians(lat))
        dy = (rios[None, :, 1] - lat) * KM_POR_GRAU_LAT
        resultado[inicio:fim] = np.sqrt(dx * dx + dy * dy).min(axis=1)

    return resultado


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()

    for caminho in (ARQUIVO_MALHA, ARQUIVO_RELEVO, ARQUIVO_RELEVO_META,
                    ARQUIVO_RIOS):
        if not caminho.exists():
            print(f"Falta {caminho.relative_to(RAIZ)}. Veja o cabeçalho deste "
                  f"arquivo para saber qual script o gera.", file=sys.stderr)
            return 1

    titulo("LENDO AS ENTRADAS")
    malha = json.loads(ARQUIVO_MALHA.read_text(encoding="utf-8"))
    print(f"  malha:  {len(malha['features']):,} municípios")

    relevo = Relevo(ARQUIVO_RELEVO, ARQUIVO_RELEVO_META)
    print(f"  relevo: grade de {relevo.largura} x {relevo.altura} "
          f"({relevo.passo}°)")

    rios, rios_grandes = carregar_rios(ARQUIVO_RIOS)
    print(f"  rios:   {len(rios):,} vértices "
          f"({len(rios_grandes):,} de rios principais)")

    titulo("MEDINDO CADA MUNICÍPIO")
    linhas = []
    for posicao, feicao in enumerate(malha["features"]):
        codigo = int(feicao["properties"]["codigo_ibge"])
        aneis = aneis_da_feicao(feicao["geometry"])
        if not aneis:
            continue

        # O maior anel é o corpo do município; os outros são ilhas e encraves,
        # que não mudam onde ele fica.
        lat_referencia = float(aneis[0][:, 1].mean())
        areas = [area_e_centroide(anel, lat_referencia) for anel in aneis]
        maior = int(np.argmax([a[0] for a in areas]))
        area_total = float(sum(a[0] for a in areas))
        _, lon, lat = areas[maior]

        registro = {
            "codigo_ibge": codigo,
            "longitude": lon,
            "latitude": lat,
            "area_km2": area_total,
        }
        registro.update(estatisticas_de_relevo(relevo, aneis[maior], lon, lat))
        linhas.append(registro)

        if (posicao + 1) % 1000 == 0:
            print(f"  {posicao + 1:,} de {len(malha['features']):,}...",
                  flush=True)

    tabela = pd.DataFrame(linhas)

    titulo("DISTÂNCIA ATÉ OS RIOS")
    tabela["distancia_rio_km"] = distancia_ate_os_rios(
        tabela["longitude"].to_numpy(), tabela["latitude"].to_numpy(), rios
    )
    tabela["distancia_rio_grande_km"] = distancia_ate_os_rios(
        tabela["longitude"].to_numpy(), tabela["latitude"].to_numpy(),
        rios_grandes
    )
    print(f"  mediana até um rio qualquer: "
          f"{tabela['distancia_rio_km'].median():.0f} km")
    print(f"  mediana até um rio principal: "
          f"{tabela['distancia_rio_grande_km'].median():.0f} km")

    titulo("CONFERINDO")
    sem_relevo = int((tabela["celulas_de_relevo"] == 0).sum())
    print(f"  municípios menores que a célula da grade: {sem_relevo:,} "
          f"({sem_relevo / len(tabela):.1%}) — usaram o ponto do centroide")
    print(f"  altitude média do país: {tabela['altitude_media_m'].mean():.0f} m")
    print(f"  área total somada: {tabela['area_km2'].sum():,.0f} km² "
          f"(o Brasil tem 8.510.000)")

    # Alguns casos conhecidos, para conferir a olho que a conta não inverteu
    # nada. Manaus é ribeirinha; Campos do Jordão é a cidade mais alta do país;
    # Santos é nível do mar.
    conhecidos = {3550308: "São Paulo", 1302603: "Manaus",
                  3509700: "Campos do Jordão", 2304400: "Fortaleza",
                  3548500: "Santos", 4314902: "Porto Alegre"}
    print()
    print(f"  {'município':<20}{'altitude':>10}{'declive':>10}"
          f"{'rio (km)':>10}{'rio grande':>12}")
    for codigo, nome in conhecidos.items():
        linha = tabela[tabela["codigo_ibge"] == codigo]
        if linha.empty:
            continue
        l = linha.iloc[0]
        print(f"  {nome:<20}{l['altitude_media_m']:>9.0f}m"
              f"{l['declividade_m_por_km']:>9.1f}"
              f"{l['distancia_rio_km']:>10.0f}"
              f"{l['distancia_rio_grande_km']:>12.0f}")

    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    tabela.to_csv(argumentos.saida, index=False)
    tamanho = argumentos.saida.stat().st_size / 1024
    print(f"\n{len(tabela):,} municípios salvos em {argumentos.saida.name} "
          f"({tamanho:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
