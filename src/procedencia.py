"""
Procedência dos dados: de onde veio o CSV usado no treino.

O projeto usa o mesmo nome de arquivo (`dados/dados.csv`) tanto para a base
sintética quanto para a real. Sem um registro, ninguém consegue saber depois
se um modelo foi treinado com dados inventados ou com dados de verdade — e
apresentar número sintético como se fosse real seria o pior erro possível
neste trabalho.

Como funciona:

  1. O gerador escreve o CSV e, ao lado, um `procedencia.json` com o hash
     SHA-256 do arquivo que acabou de gerar.
  2. O treinamento pergunta a este módulo qual é a origem do CSV atual.
  3. Se o hash do CSV bate com o registrado, a base é a sintética.
     Se não bate (ou não há registro), o arquivo foi substituído por outro —
     tratado como origem desconhecida, nunca como sintética.

A origem fica gravada nos metadados do modelo e é exibida pela API.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_PROCEDENCIA = RAIZ / "dados" / "procedencia.json"

SINTETICO = "sintetico"
DESCONHECIDA = "desconhecida"

AVISO_SINTETICO = (
    "Modelo treinado com dados SINTÉTICOS (inventados por script). "
    "Os números servem para verificar se o sistema funciona e NÃO valem "
    "como resultado sobre desastres reais no Brasil."
)


def hash_arquivo(caminho: Path) -> str:
    """SHA-256 do arquivo, lido em blocos para não carregar tudo na memória."""
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(65536), b""):
            digest.update(bloco)
    return digest.hexdigest()


def registrar_sintetico(caminho_csv: Path, semente: int, anos: tuple[int, int],
                        linhas: int) -> Path:
    """Grava o registro de que o CSV indicado foi gerado por script."""
    registro = {
        "origem": SINTETICO,
        "arquivo": caminho_csv.name,
        "hash_sha256": hash_arquivo(caminho_csv),
        "linhas": linhas,
        "semente": semente,
        "periodo": {"ano_inicial": anos[0], "ano_final": anos[1]},
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerado_por": "dados/gerar_dados_sinteticos.py",
        "aviso": AVISO_SINTETICO,
    }

    ARQUIVO_PROCEDENCIA.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_PROCEDENCIA.write_text(
        json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ARQUIVO_PROCEDENCIA


def identificar(caminho_csv: Path) -> dict:
    """
    Descobre a origem do CSV informado.

    Devolve sempre um dicionário com 'origem' e 'hash_sha256'. A origem só é
    'sintetico' quando o hash confere com o registro — na dúvida, o resultado
    é 'desconhecida', que é o lado seguro.
    """
    hash_atual = hash_arquivo(caminho_csv)
    resultado = {"origem": DESCONHECIDA, "hash_sha256": hash_atual, "aviso": None}

    if not ARQUIVO_PROCEDENCIA.exists():
        return resultado

    try:
        registro = json.loads(ARQUIVO_PROCEDENCIA.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return resultado

    mesmo_arquivo = registro.get("arquivo") == caminho_csv.name
    mesmo_conteudo = registro.get("hash_sha256") == hash_atual

    if mesmo_arquivo and mesmo_conteudo:
        resultado["origem"] = SINTETICO
        resultado["aviso"] = AVISO_SINTETICO
        resultado["semente"] = registro.get("semente")
        resultado["gerado_em"] = registro.get("gerado_em")

    return resultado


def e_sintetico(caminho_csv: Path) -> bool:
    """Atalho de leitura: o CSV informado é a base sintética?"""
    return identificar(caminho_csv)["origem"] == SINTETICO
