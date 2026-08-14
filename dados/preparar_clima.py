"""
Prepara os dados climáticos do INMET para o projeto.

Como executar (a partir da raiz do projeto):
    python dados/preparar_clima.py

O que faz:
    1. Baixa (se faltar) a lista de municípios do IBGE
    2. Lê os CSVs das estações do INMET em dados/bruto/inmet/
    3. Agrega os dados horários em valores mensais por estação
    4. Casa cada estação com seu município e espalha a medição para todos os
       municípios, do nível mais próximo ao mais distante
    5. Calcula a normal climatológica de 2000–2009
    6. Escreve dados/clima_mensal.csv e dados/clima_normais.csv

Antes de rodar, baixe os dados do INMET
---------------------------------------
1. Abra https://portal.inmet.gov.br/dadoshistoricos
2. Baixe os anos que quiser (um ZIP por ano). Para acompanhar o período do
   Atlas com normal climatológica, o ideal é de 2000 a 2025.
3. Descompacte TODOS os ZIPs dentro de `dados/bruto/inmet/`.
   Não importa se ficarem em subpastas por ano — a busca é recursiva.

Cada ZIP tem de 40 a 120 MB. Baixar tudo leva tempo; comece por alguns anos
recentes se quiser só testar o encanamento.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import inmet, regioes  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_CLIMA = RAIZ / "dados" / "clima_mensal.csv"
SAIDA_NORMAIS = RAIZ / "dados" / "clima_normais.csv"


def garantir_lista_ibge(caminho: Path) -> None:
    """Baixa a lista de municípios do IBGE se ela ainda não estiver aqui."""
    if caminho.exists():
        return

    print(f"Baixando a lista de municípios do IBGE...")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(regioes.URL_IBGE, caminho)
    except OSError as erro:
        raise regioes.ErroRegioes(
            f"Não consegui baixar a lista do IBGE ({erro}).\n\n"
            f"Baixe manualmente e salve em {caminho}:\n  {regioes.URL_IBGE}"
        ) from erro

    tamanho = caminho.stat().st_size / 1024 / 1024
    print(f"  salvo em {caminho.name} ({tamanho:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepara os dados climáticos do INMET."
    )
    parser.add_argument("--inmet", type=Path, default=inmet.PASTA_INMET,
                        help="pasta com os CSVs das estações")
    parser.add_argument("--normal-anos", nargs=2, type=int,
                        default=[inmet.NORMAL_ANO_INICIAL, inmet.NORMAL_ANO_FINAL],
                        metavar=("INICIO", "FIM"),
                        help="período da normal climatológica (padrão: 2000 2009)")
    parser.add_argument("--minimo-valido", type=float,
                        default=inmet.MINIMO_HORAS_VALIDAS,
                        help="fração mínima de horas com registro (padrão: 0.5)")
    argumentos = parser.parse_args()

    try:
        garantir_lista_ibge(regioes.ARQUIVO_MUNICIPIOS)
        municipios = regioes.carregar_municipios()
        print(f"Municípios do IBGE: {len(municipios):,}")

        print(f"\nLendo as estações em {argumentos.inmet}...")
        lidos = [0]

        def progresso(arquivo, ok, falhas):
            lidos[0] += 1
            if lidos[0] % 100 == 0:
                print(f"  {lidos[0]} arquivos... ({falhas} com falha)")

        mensal = inmet.carregar_pasta(
            argumentos.inmet, argumentos.minimo_valido, ao_ler=progresso
        )
    except (inmet.ErroInmet, regioes.ErroRegioes) as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    falhas = mensal.attrs["arquivos_com_falha"]
    print(f"\n  {mensal.attrs['arquivos_lidos']} estações lidas")
    print(f"  {len(falhas)} arquivo(s) com falha")
    print(f"  {mensal.attrs['meses_descartados']} mês(es) descartado(s) por "
          f"registro incompleto")
    print(f"  {len(mensal):,} medições mensais, "
          f"{mensal['ano'].min()}–{mensal['ano'].max()}")

    if falhas:
        print("\n  Primeiras falhas:")
        for nome, motivo in falhas[:3]:
            print(f"    {nome}: {motivo}")

    # --- Casamento com os municípios ---------------------------------------
    estacoes = mensal[["estacao", "uf"]].drop_duplicates()
    casadas = regioes.casar_estacoes(estacoes, municipios)
    cobertura = regioes.resumir_cobertura(casadas, municipios)

    print(f"\nEstações casadas com município: "
          f"{cobertura['estacoes'] - cobertura['estacoes_sem_municipio']} "
          f"de {cobertura['estacoes']}")
    print("\nCobertura dos municípios do país:")
    print(f"  com estação própria ........ {cobertura['municipios_com_estacao_propria']:>5,}")
    print(f"  via região imediata ........ {cobertura['municipios_via_regiao_imediata']:>5,}")
    print(f"  via região intermediária ... {cobertura['municipios_via_regiao_intermediaria']:>5,}")
    print(f"  via UF ..................... {cobertura['municipios_via_uf']:>5,}")
    print(f"  total de municípios ........ {cobertura['total_municipios']:>5,}")

    try:
        clima = inmet.atribuir_a_municipios(mensal, casadas, municipios)
    except inmet.ErroInmet as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    print(f"\n{len(clima):,} linhas de clima por município e mês")
    print(f"{clima.attrs['municipios_sem_clima']:,} município(s) sem nenhuma fonte")
    print("\nDe onde veio a medição de cada linha:")
    for nivel, quantidade in clima["fonte_clima"].value_counts().items():
        print(f"  {nivel:<24} {quantidade:>9,}  ({quantidade / len(clima):.1%})")

    # --- Normal climatológica ----------------------------------------------
    normais = inmet.calcular_normais(mensal, *argumentos.normal_anos)
    if normais.empty:
        print(f"\n[aviso] Sem dados de {argumentos.normal_anos[0]}–"
              f"{argumentos.normal_anos[1]} para calcular a normal.")
        print("        A anomalia de chuva não poderá ser usada. Baixe os anos")
        print("        antigos do INMET se quiser essa variável.")
    else:
        print(f"\nNormal climatológica de {argumentos.normal_anos[0]}–"
              f"{argumentos.normal_anos[1]}: {len(normais):,} combinações "
              f"estação × mês")

    SAIDA_CLIMA.parent.mkdir(parents=True, exist_ok=True)
    clima.to_csv(SAIDA_CLIMA, index=False, encoding="utf-8")
    normais.to_csv(SAIDA_NORMAIS, index=False, encoding="utf-8")

    print(f"\nSalvos:")
    print(f"  {SAIDA_CLIMA.name} ({SAIDA_CLIMA.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  {SAIDA_NORMAIS.name}")

    print("\nPróximo passo: juntar o clima ao dataset de treino.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
