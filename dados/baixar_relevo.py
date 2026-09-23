"""
Baixa a altimetria do Brasil — a altura do terreno, metro a metro.

Como executar (a partir da raiz do projeto):
    python dados/baixar_relevo.py

Gera dois arquivos, que VÃO para o repositório:
    dados/relevo_brasil.bin    a grade de altitudes (~7,6 MB)
    dados/relevo_brasil.json   onde essa grade fica no mapa e o que há nela

De onde vem o dado
------------------
Dos "terrain tiles" da Amazon (projeto Terrarium, herdado do Mapzen): uma
composição aberta de SRTM, ASTER, GMTED e levantamentos nacionais, distribuída
sem cadastro e sem chave. Cada tile é um PNG 256x256 em que a cor não é cor
nenhuma — é a altitude codificada:

    altura_em_metros = vermelho * 256 + verde + azul / 256 - 32768

Este script baixa os tiles que cobrem o Brasil, reamostra tudo para uma grade
regular de latitude e longitude e guarda as altitudes como inteiros de 16 bits.
O navegador lê esse bloco direto, sem conversão nenhuma, e calcula o
sombreamento na hora de desenhar.

Por que uma grade regular, e não os tiles
-----------------------------------------
Os tiles vêm em projeção Mercator, em que um grau de latitude ocupa cada vez
mais pixels conforme se afasta do Equador. O mapa do projeto é plano em
latitude e longitude. Reprojetar no navegador a cada desenho custaria caro e
teria que ser refeito a cada zoom; reprojetar uma vez aqui custa um minuto e
nunca mais.

Passo de 0,02° (~2,2 km)
------------------------
O dobro da resolução do mapa do país inteiro, e de propósito. Num mapa do
Brasil todo, 0,04° bastaria: são ~40° de largura em 1000 px, ou 25 px por grau,
que é exatamente o que uma grade de 0,04° entrega. Mas o mapa não fica parado
no país inteiro — ele voa até o estado, e é lá que o relevo interessa, com a
serra ocupando a tela. Com 0,04° o terreno virava um borrão nesse zoom, e o
modo 3D mostrava degraus de 4 km em vez de encostas.

Para quem preferir um repositório menor, `--passo 0.04 --zoom 6` devolve a
grade antiga de 2 MB, que continua boa para o mapa do país.

O mar entra como zero
---------------------
Os tiles trazem também a profundidade do oceano, que chega a -4.000 m. Como
nenhum ponto do Brasil fica abaixo do nível do mar, deixar a batimetria no
arquivo só criaria um degrau de 4 km na linha da costa — e um degrau vira um
risco brilhante no sombreamento, exatamente em cima do litoral. Zerar o que
está abaixo do nível do mar não perde nada e deixa a costa lisa.
"""

import argparse
import json
import math
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_GRADE = RAIZ / "dados" / "relevo_brasil.bin"
SAIDA_META = RAIZ / "dados" / "relevo_brasil.json"

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

# Um retângulo com folga em volta do país. O Brasil vai de -73,99 (Acre) a
# -34,79 (Ponta do Seixas, PB) e de +5,27 (Monte Caburaí) a -33,75 (Chuí).
LON_OESTE, LON_LESTE = -74.5, -34.0
LAT_NORTE, LAT_SUL = 5.5, -34.0
PASSO = 0.02

ZOOM_PADRAO = 7          # 2^7 tiles em volta do mundo: ~1,2 km por pixel aqui
LADO_TILE = 256


# ---------------------------------------------------------------------------
# PNG na unha
#
# O projeto não depende de Pillow, e não vale a pena passar a depender por
# causa de um script que roda uma vez. Um PNG sem entrelaçamento é honestamente
# simples: cabeçalho, dados comprimidos com zlib e, dentro deles, cada linha
# começando com um byte que diz como ela foi prevista a partir da linha de cima
# e do pixel da esquerda. Desfazer essa previsão é o trabalho todo.
# ---------------------------------------------------------------------------

ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"


def decodificar_png(dados: bytes) -> np.ndarray:
    """Devolve a imagem como um array (altura, largura, canais) de bytes."""
    if dados[:8] != ASSINATURA_PNG:
        raise ValueError("não é um PNG")

    pedacos, posicao = {}, 8
    comprimidos = bytearray()
    while posicao < len(dados):
        (tamanho,) = struct.unpack(">I", dados[posicao:posicao + 4])
        tipo = dados[posicao + 4:posicao + 8]
        corpo = dados[posicao + 8:posicao + 8 + tamanho]
        if tipo == b"IDAT":
            comprimidos += corpo        # o IDAT costuma vir partido em vários
        else:
            pedacos[tipo] = corpo
        posicao += 12 + tamanho

    largura, altura, bits, cor, _, _, entrelacado = struct.unpack(
        ">IIBBBBB", pedacos[b"IHDR"])
    if bits != 8 or entrelacado or cor not in (2, 6):
        raise ValueError(f"PNG fora do esperado (bits={bits}, cor={cor})")

    canais = 3 if cor == 2 else 4
    cru = zlib.decompress(bytes(comprimidos))
    linha_bytes = largura * canais

    imagem = np.empty((altura, linha_bytes), dtype=np.uint8)
    anterior = bytearray(linha_bytes)
    posicao = 0

    for y in range(altura):
        filtro = cru[posicao]
        linha = bytearray(cru[posicao + 1:posicao + 1 + linha_bytes])
        posicao += 1 + linha_bytes

        if filtro == 1:                                     # Sub
            for i in range(canais, linha_bytes):
                linha[i] = (linha[i] + linha[i - canais]) & 0xFF
        elif filtro == 2:                                   # Up
            for i in range(linha_bytes):
                linha[i] = (linha[i] + anterior[i]) & 0xFF
        elif filtro == 3:                                   # Average
            for i in range(linha_bytes):
                esquerda = linha[i - canais] if i >= canais else 0
                linha[i] = (linha[i] + ((esquerda + anterior[i]) >> 1)) & 0xFF
        elif filtro == 4:                                   # Paeth
            for i in range(linha_bytes):
                a = linha[i - canais] if i >= canais else 0
                b = anterior[i]
                c = anterior[i - canais] if i >= canais else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                previsto = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                linha[i] = (linha[i] + previsto) & 0xFF
        elif filtro != 0:
            raise ValueError(f"filtro PNG desconhecido: {filtro}")

        imagem[y] = np.frombuffer(bytes(linha), dtype=np.uint8)
        anterior = linha

    return imagem.reshape(altura, largura, canais)


# ---------------------------------------------------------------------------
# Mercator
# ---------------------------------------------------------------------------

def para_tile_x(lon, zoom):
    return (lon + 180.0) / 360.0 * (1 << zoom)


def para_tile_y(lat, zoom):
    radianos = np.radians(lat)
    return (1.0 - np.log(np.tan(radianos) + 1.0 / np.cos(radianos))
            / math.pi) / 2.0 * (1 << zoom)


def baixar_tile(zoom: int, x: int, y: int) -> bytes:
    """
    Busca um tile.

    Como no resto do projeto, quem fala com a rede é o `curl`. Em rede de
    escola ou empresa com inspeção de certificado, a checagem de revogação do
    Windows falha antes de a conexão sair; a segunda tentativa desliga só essa
    checagem, que é o suficiente para passar.
    """
    comando = ["curl", "-sS", "-m", "120", "--retry", "2",
               URL.format(z=zoom, x=x, y=y)]
    resultado = subprocess.run(comando, capture_output=True)

    if resultado.returncode != 0:
        resultado = subprocess.run(comando + ["--ssl-no-revoke"],
                                   capture_output=True)
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.decode(errors="replace").strip()[:120])
    return resultado.stdout


def montar_mosaico(zoom: int) -> tuple[np.ndarray, int, int]:
    """Baixa todos os tiles do retângulo e costura num array só de altitudes."""
    x0 = int(math.floor(para_tile_x(LON_OESTE, zoom)))
    x1 = int(math.floor(para_tile_x(LON_LESTE, zoom)))
    y0 = int(math.floor(para_tile_y(LAT_NORTE, zoom)))
    y1 = int(math.floor(para_tile_y(LAT_SUL, zoom)))

    colunas, linhas = x1 - x0 + 1, y1 - y0 + 1
    total = colunas * linhas
    print(f"Zoom {zoom}: {total} tiles ({colunas} x {linhas}), "
          f"{colunas * LADO_TILE} x {linhas * LADO_TILE} pontos")

    mosaico = np.zeros((linhas * LADO_TILE, colunas * LADO_TILE),
                       dtype=np.float32)
    baixados = 0

    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            try:
                imagem = decodificar_png(baixar_tile(zoom, x, y))
            except (RuntimeError, ValueError, zlib.error) as erro:
                print(f"  tile {x}/{y}: FALHOU — {erro}", file=sys.stderr)
                continue

            # A fórmula do Terrarium. Fica em float porque o azul carrega a
            # fração do metro, e arredondar antes da reamostragem jogaria fora
            # justamente a precisão que o sombreamento usa.
            altura = (imagem[:, :, 0].astype(np.float32) * 256.0
                      + imagem[:, :, 1].astype(np.float32)
                      + imagem[:, :, 2].astype(np.float32) / 256.0
                      - 32768.0)

            topo = (y - y0) * LADO_TILE
            lado = (x - x0) * LADO_TILE
            mosaico[topo:topo + LADO_TILE, lado:lado + LADO_TILE] = altura

            baixados += 1
            if baixados % 10 == 0 or baixados == total:
                print(f"  {baixados}/{total} tiles", flush=True)
            time.sleep(0.05)   # cortesia com o servidor

    if not baixados:
        raise RuntimeError("nenhum tile foi baixado")
    if baixados < total:
        print(f"[aviso] {total - baixados} tile(s) faltando: o relevo terá "
              f"buracos. Rode de novo.", file=sys.stderr)

    return mosaico, x0, y0


def reamostrar(mosaico: np.ndarray, zoom: int, x0: int, y0: int) -> np.ndarray:
    """Passa do mosaico em Mercator para a grade regular de lat/lon."""
    largura = int(round((LON_LESTE - LON_OESTE) / PASSO)) + 1
    altura = int(round((LAT_NORTE - LAT_SUL) / PASSO)) + 1

    lons = LON_OESTE + np.arange(largura) * PASSO
    lats = LAT_NORTE - np.arange(altura) * PASSO

    # Onde cada ponto da grade cai dentro do mosaico, em pixels.
    x = para_tile_x(lons, zoom) * LADO_TILE - x0 * LADO_TILE
    y = para_tile_y(lats, zoom) * LADO_TILE - y0 * LADO_TILE

    altura_px, largura_px = mosaico.shape
    x = np.clip(x, 0, largura_px - 1.001)
    y = np.clip(y, 0, altura_px - 1.001)

    xe = np.floor(x).astype(np.int32)
    ys = np.floor(y).astype(np.int32)
    fx = (x - xe).astype(np.float32)
    fy = (y - ys).astype(np.float32)

    # Bilinear: a média dos quatro vizinhos, pesada pela distância. Vizinho
    # mais próximo deixaria degraus visíveis no sombreamento, porque a grade é
    # mais fina que o mosaico perto do Equador.
    superior = (mosaico[ys][:, xe] * (1 - fx) + mosaico[ys][:, xe + 1] * fx)
    inferior = (mosaico[ys + 1][:, xe] * (1 - fx)
                + mosaico[ys + 1][:, xe + 1] * fx)
    grade = superior * (1 - fy[:, None]) + inferior * fy[:, None]

    return np.maximum(grade, 0.0)      # o mar entra como zero


def escrever_metadados(alturas: np.ndarray, zoom: int, arquivo: Path) -> dict:
    """Descreve a grade num JSON ao lado dela, para o mapa saber lê-la."""
    maior = int(alturas.max())
    linha, coluna = np.unravel_index(int(alturas.argmax()), alturas.shape)

    meta = {
        "fonte": "Terrarium terrain tiles (AWS) — SRTM, ASTER, GMTED e outros",
        "arquivo": arquivo.name,
        "tipo": "int16 little-endian, sem cabeçalho, linha a linha de norte a sul",
        "largura": int(alturas.shape[1]),
        "altura": int(alturas.shape[0]),
        "passo_graus": PASSO,
        "passo_km_aprox": round(PASSO * 111.32, 1),
        "lon_oeste": LON_OESTE,
        "lat_norte": LAT_NORTE,
        "lon_leste": round(LON_OESTE + (alturas.shape[1] - 1) * PASSO, 4),
        "lat_sul": round(LAT_NORTE - (alturas.shape[0] - 1) * PASSO, 4),
        # "da grade", e não "do Brasil": o retângulo é maior que o país e
        # encosta nos Andes, que passam dos 6.000 m. O mapa recorta o desenho
        # na fronteira, então esse valor não chega a aparecer — mas chamá-lo de
        # altitude máxima do Brasil seria falso.
        "altitude_maxima_grade_m": maior,
        "altitude_maxima_grade_em": [
            round(float(LAT_NORTE - linha * PASSO), 3),
            round(float(LON_OESTE + coluna * PASSO), 3),
        ],
        "zoom_dos_tiles": zoom,
        "observacoes": [
            "Abaixo do nível do mar tudo virou zero: nenhum ponto do Brasil "
            "fica abaixo dele, e a batimetria só criaria um degrau artificial "
            "na linha da costa.",
            "O retângulo cobre o Brasil com folga e entra em países vizinhos. "
            "O mapa recorta o desenho no contorno do país.",
f"Cada ponto da grade é a média de ~{round(PASSO * 111.32, 1)} km de "
            "terreno, então pico estreito aparece mais baixo que a altitude "
            "real do cume: o Pico da Neblina (2.995 m) sai por volta de "
            "1.760 m. Serve para mostrar a forma do relevo, não para medir "
            "cume.",
        ],
    }
    SAIDA_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return meta


def main() -> int:
    # O passo é lido por três funções deste módulo. Enfiá-lo como parâmetro em
    # todas elas, só para permitir uma opção de linha de comando, encheria as
    # assinaturas sem ninguém ganhar nada: o script roda uma vez e morre.
    global PASSO

    parser = argparse.ArgumentParser(
        description="Baixa a altimetria do Brasil e monta a grade do relevo.")
    parser.add_argument("--zoom", type=int, default=ZOOM_PADRAO,
                        help="zoom dos tiles (padrão 7; 6 baixa 4x menos)")
    parser.add_argument("--passo", type=float, default=PASSO,
                        help=("passo da grade em graus (padrão 0.02, ~2,2 km, "
                              "~7,6 MB). 0.04 devolve a grade de 2 MB, boa "
                              "para o mapa do país inteiro e fraca no zoom; "
                              "use junto com --zoom 6"))
    parser.add_argument("--saida", type=Path, default=SAIDA_GRADE)
    argumentos = parser.parse_args()
    PASSO = argumentos.passo

    try:
        mosaico, x0, y0 = montar_mosaico(argumentos.zoom)
    except RuntimeError as erro:
        print(f"Falhou: {erro}", file=sys.stderr)
        return 1

    print("Reamostrando para a grade de latitude e longitude...")
    grade = reamostrar(mosaico, argumentos.zoom, x0, y0)
    alturas = np.round(grade).astype(np.int16)

    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_bytes(alturas.astype("<i2").tobytes())
    meta = escrever_metadados(alturas, argumentos.zoom, argumentos.saida)

    tamanho = argumentos.saida.stat().st_size / 1024 / 1024
    print(f"\nGrade de {meta['largura']} x {meta['altura']} salva em "
          f"{argumentos.saida.name} ({tamanho:.1f} MB)")
    print(f"Altitude máxima na grade: {meta['altitude_maxima_grade_m']} m "
          f"(em {meta['altitude_maxima_grade_em']} — fora do Brasil, nos Andes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
