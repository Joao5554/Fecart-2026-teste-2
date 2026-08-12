"""
Monta o pacote para apresentar o projeto em outro computador.

Como executar (a partir da raiz do projeto):
    python ferramentas/preparar_apresentacao.py
    python ferramentas/preparar_apresentacao.py --com-bibliotecas   (funciona sem internet)

Por que existe
--------------
A pasta do projeto tem mais de 500 MB, mas quase tudo é descartável na hora de
apresentar:

    .venv/            336 MB  recriado com pip, não se copia entre máquinas
    dados/bruto/       82 MB  base crua do Atlas, só serve para treinar
    dados/dados.csv    24 MB  dataset de treino, só serve para treinar

Para RODAR o sistema bastam três coisas: o código, o modelo treinado e o
histórico de ocorrências que a API consulta. Este script separa exatamente
isso, e o resultado fica em torno de 30 MB — cabe em qualquer pendrive e
copia em segundos.
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "apresentacao"

# Código e configuração: o que faz o sistema funcionar.
PASTAS_CODIGO = ["src", "backend", "frontend", "treinamento", "testes"]
ARQUIVOS_CODIGO = ["requirements.txt", "README.md", ".gitignore"]

# Os dois arquivos gerados de que a API precisa em execução.
ARQUIVOS_GERADOS = [
    ("modelo/modelo.pkl", "o modelo treinado"),
    ("modelo/metadados.json", "métricas e procedência do modelo"),
    ("dados/ocorrencias.csv", "histórico consultado pela API"),
]

LEIAME = """\
# Como rodar esta apresentação

Pacote pronto do projeto Fecart 2026. O modelo **já está treinado**: não é
preciso baixar a base do Atlas nem treinar de novo.

## 1. Criar o ambiente virtual

```
python -m venv .venv
```

## 2. Ativar (Windows)

```
.venv\\Scripts\\activate
```

Se aparecer erro de "execução de scripts desabilitada", rode uma vez:

```
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

e abra um novo terminal.

## 3. Instalar as bibliotecas

{instrucao_instalacao}

## 4. Subir o sistema

```
uvicorn backend.app:app --reload
```

## 5. Abrir no navegador

    http://127.0.0.1:8000/app

A documentação da API fica em http://127.0.0.1:8000/docs

---

## Se algo der errado

**"O modelo ainda não foi treinado"** — a pasta `modelo/` não veio junto.
Copie o pacote inteiro de novo.

**A página abre mas o formulário não funciona** — você abriu o arquivo
`frontend/index.html` direto. Use o endereço `http://127.0.0.1:8000/app`,
com o servidor no ar.

**Quero treinar de novo** — aí sim é preciso a base bruta do Atlas
(<https://atlasdigital.mi.gov.br>) em `dados/bruto/`, e rodar:

```
python dados/preparar_dados.py
python treinamento/treinar_modelo.py
```
"""


def remover_pasta(caminho: Path, tentativas: int = 4) -> None:
    """
    Apaga uma pasta, insistindo quando o Windows a mantém travada.

    Este projeto costuma ficar dentro do OneDrive, que segura arquivos
    enquanto sincroniza. Sem as tentativas, refazer o pacote falha com
    "Acesso negado" em um diretório qualquer.
    """
    def liberar(func, alvo, _erro):
        os.chmod(alvo, stat.S_IWRITE)
        func(alvo)

    for tentativa in range(tentativas):
        try:
            shutil.rmtree(caminho, onexc=liberar)
            return
        except (PermissionError, OSError):
            if tentativa == tentativas - 1:
                raise
            time.sleep(1.5)


def copiar(origem: Path, destino: Path) -> int:
    """Copia arquivo ou pasta e devolve o total em bytes."""
    if origem.is_dir():
        shutil.copytree(
            origem, destino,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        return sum(f.stat().st_size for f in destino.rglob("*") if f.is_file())

    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)
    return destino.stat().st_size


def baixar_bibliotecas(destino: Path) -> int:
    """
    Baixa os pacotes do requirements.txt para instalação sem internet.

    Útil quando o computador da escola é restrito ou está offline: em vez de
    `pip install -r requirements.txt`, usa-se a pasta baixada.
    """
    destino.mkdir(parents=True, exist_ok=True)
    print("\nBaixando as bibliotecas (pode demorar)...")

    resultado = subprocess.run(
        [sys.executable, "-m", "pip", "download",
         "-r", str(RAIZ / "requirements.txt"), "-d", str(destino)],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        print("  [aviso] não foi possível baixar as bibliotecas:")
        erro = (resultado.stderr or "").strip().splitlines()
        print("  " + (erro[-1][:200] if erro else "erro desconhecido"))
        shutil.rmtree(destino, ignore_errors=True)
        return 0

    return sum(f.stat().st_size for f in destino.rglob("*") if f.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monta o pacote leve para apresentar em outro computador."
    )
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO,
                        help="pasta a criar (padrão: apresentacao/)")
    parser.add_argument("--com-bibliotecas", action="store_true",
                        help="inclui os pacotes Python, para instalar sem internet")
    parser.add_argument("--zip", action="store_true",
                        help="compacta o resultado em um .zip")
    args = parser.parse_args()

    faltando = [
        f"  {caminho}  ({descricao})"
        for caminho, descricao in ARQUIVOS_GERADOS
        if not (RAIZ / caminho).exists()
    ]
    if faltando:
        print("Faltam arquivos gerados:\n" + "\n".join(faltando), file=sys.stderr)
        print("\nRode antes:\n  python dados/preparar_dados.py"
              "\n  python treinamento/treinar_modelo.py", file=sys.stderr)
        return 1

    if args.saida.exists():
        try:
            remover_pasta(args.saida)
        except OSError as erro:
            print(f"Não consegui apagar {args.saida} ({erro}).\n"
                  "Feche programas que estejam usando a pasta (ou pause o "
                  "OneDrive) e tente de novo.", file=sys.stderr)
            return 1
    args.saida.mkdir(parents=True)

    print(f"Montando o pacote em {args.saida.name}/\n")
    total = 0

    for pasta in PASTAS_CODIGO:
        if (RAIZ / pasta).exists():
            tamanho = copiar(RAIZ / pasta, args.saida / pasta)
            total += tamanho
            print(f"  {pasta + '/':<26} {tamanho / 1024:>8,.0f} KB")

    for arquivo in ARQUIVOS_CODIGO:
        if (RAIZ / arquivo).exists():
            total += copiar(RAIZ / arquivo, args.saida / arquivo)

    print()
    for caminho, descricao in ARQUIVOS_GERADOS:
        tamanho = copiar(RAIZ / caminho, args.saida / caminho)
        total += tamanho
        print(f"  {caminho:<26} {tamanho / 1024 / 1024:>8.1f} MB  {descricao}")

    # A pasta dados/bruto precisa existir para o projeto poder ser retreinado lá.
    (args.saida / "dados" / "bruto").mkdir(parents=True, exist_ok=True)
    (args.saida / "dados" / "bruto" / ".gitkeep").touch()

    instrucao = "```\npip install -r requirements.txt\n```"
    if args.com_bibliotecas:
        tamanho = baixar_bibliotecas(args.saida / "bibliotecas")
        if tamanho:
            total += tamanho
            print(f"\n  {'bibliotecas/':<26} {tamanho / 1024 / 1024:>8.1f} MB  "
                  f"instalação sem internet")
            instrucao = (
                "As bibliotecas vieram junto, então **não precisa de internet**:\n\n"
                "```\npip install --no-index --find-links=bibliotecas "
                "-r requirements.txt\n```"
            )

    (args.saida / "LEIAME.md").write_text(
        LEIAME.format(instrucao_instalacao=instrucao), encoding="utf-8"
    )

    print(f"\n{'TOTAL':<26} {total / 1024 / 1024:>8.1f} MB")

    if args.zip:
        print("\nCompactando...")
        caminho_zip = shutil.make_archive(str(args.saida), "zip", args.saida)
        tamanho_zip = Path(caminho_zip).stat().st_size / 1024 / 1024
        print(f"  {Path(caminho_zip).name}  ({tamanho_zip:.1f} MB)")

    print("\nCopie essa pasta para o pendrive. As instruções de uso estão")
    print("em LEIAME.md, dentro dela.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
