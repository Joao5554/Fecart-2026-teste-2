"""
Prepara o dataset de treino a partir do Atlas de Desastres (base REAL).

Como executar (a partir da raiz do projeto):
    python dados/preparar_dados.py
    python dados/preparar_dados.py --anos 2010 2025 --negativos 3

O que faz:
    1. Lê o arquivo bruto do Atlas em dados/bruto/
    2. Limpa, mapeia as tipologias e monta linhas município x mês x tipo
    3. Calcula as features históricas sem vazamento temporal
    4. Escreve dados/dados.csv e registra a procedência como REAL

Onde conseguir o arquivo bruto:
    https://atlasdigital.mi.gov.br — baixe a base consolidada
    (BD_Atlas_..._Consolidado.csv) e salve em dados/bruto/.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import atlas, clima, esquema, procedencia  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PASTA_BRUTO = RAIZ / "dados" / "bruto"
SAIDA_PADRAO = RAIZ / "dados" / "dados.csv"
ARQUIVO_CLIMA = RAIZ / "dados" / "clima_mensal.csv"

FONTE = "Atlas Digital de Desastres no Brasil — S2iD/SEDEC/MIDR"


def juntar_clima(dados: pd.DataFrame, caminho: Path) -> pd.DataFrame:
    """
    Acrescenta as variáveis de chuva, se os dados do INMET já tiverem sido
    preparados. Sem eles, o dataset segue sem clima e o modelo usa apenas
    histórico e sazonalidade.
    """
    if not caminho.exists():
        print(f"\n[sem clima] {caminho.name} não encontrado.")
        print("            As colunas de chuva entram vazias, e o modelo segue")
        print("            usando apenas histórico e sazonalidade.")
        print("            Para preenchê-las: python dados/preparar_clima.py")

        # As colunas precisam existir mesmo vazias: o contrato de dados as
        # declara, e o pipeline do modelo sabe imputar valor faltante. Sem
        # isso, quem não baixou os 1,8 GB do INMET não conseguiria treinar.
        dados = dados.copy()
        for coluna in clima.COLUNAS_CLIMA:
            dados[coluna] = np.nan
        dados["meses_de_clima_disponiveis"] = 0
        return dados

    print(f"\nJuntando o clima de {caminho.name}...")
    tabela_clima = pd.read_csv(caminho)
    com_clima = clima.adicionar_features(dados, tabela_clima)

    cobertura = clima.resumir_cobertura(com_clima)
    print(f"  {cobertura['com_chuva_do_mes_anterior']:,} de "
          f"{cobertura['linhas']:,} linhas com chuva do mês anterior "
          f"({cobertura['pct_com_chuva']:.1%})")
    print(f"  {cobertura['com_anomalia']:,} com anomalia em relação à normal "
          f"({cobertura['pct_com_anomalia']:.1%})")
    print(f"  {cobertura['tres_meses_completos']:,} com os três meses anteriores "
          f"completos")

    return com_clima


def localizar_arquivo_bruto(pasta: Path) -> Path:
    """Encontra o CSV do Atlas na pasta de dados brutos."""
    candidatos = sorted(pasta.glob("*.csv")) if pasta.exists() else []
    if not candidatos:
        raise atlas.ErroAtlas(
            f"Nenhum CSV encontrado em {pasta}.\n\n"
            "Baixe a base consolidada do Atlas Digital de Desastres em\n"
            "  https://atlasdigital.mi.gov.br\n"
            f"e salve o arquivo em {pasta}."
        )
    # O nome do Atlas traz a data; o último em ordem alfabética é o mais novo.
    return candidatos[-1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte o Atlas de Desastres no dataset de treino."
    )
    parser.add_argument("--bruto", type=Path, default=None,
                        help="caminho do CSV bruto do Atlas (padrão: dados/bruto/)")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO,
                        help="caminho do CSV de treino a gerar")
    parser.add_argument("--anos", nargs=2, type=int, default=[2010, 2025],
                        metavar=("INICIO", "FIM"),
                        help="período a incluir (padrão: 2010 2025)")
    parser.add_argument("--negativos", type=int, default=3,
                        help="meses sem desastre por mês com desastre (padrão: 3)")
    parser.add_argument("--semente", type=int, default=42,
                        help="semente da amostragem, para ser reproduzível")
    parser.add_argument("--clima", type=Path, default=ARQUIVO_CLIMA,
                        help="CSV de clima mensal (gerado por preparar_clima.py)")
    parser.add_argument("--sem-clima", action="store_true",
                        help="ignora os dados de chuva, mesmo se existirem")
    args = parser.parse_args()

    try:
        bruto = args.bruto or localizar_arquivo_bruto(PASTA_BRUTO)
        print(f"Arquivo bruto: {bruto.name}")

        ocorrencias = atlas.carregar_atlas(bruto)
        print(f"  {len(ocorrencias):,} ocorrências aproveitadas "
              f"({ocorrencias['ano'].min()}–{ocorrencias['ano'].max()}), "
              f"{ocorrencias['codigo_ibge'].nunique():,} municípios")
        print(f"  tipologias descartadas: {', '.join(atlas.TIPOLOGIAS_DESCARTADAS)}")

        print("\nMontando o dataset (features históricas sem vazamento)...")
        dados = atlas.construir_dataset(
            ocorrencias,
            ano_inicial=args.anos[0],
            ano_final=args.anos[1],
            negativos_por_positivo=args.negativos,
            semente=args.semente,
        )
    except atlas.ErroAtlas as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    if not args.sem_clima:
        dados = juntar_clima(dados, args.clima)

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    dados.to_csv(args.saida, index=False, encoding="utf-8")

    # As ocorrências limpas ficam ao lado do dataset: é delas que a API calcula
    # o histórico de um município na hora da consulta, usando exatamente a
    # mesma função do treino.
    caminho_ocorrencias = args.saida.parent / "ocorrencias.csv"
    ocorrencias.to_csv(caminho_ocorrencias, index=False, encoding="utf-8")
    print(f"Ocorrências limpas salvas em {caminho_ocorrencias.name} "
          f"({len(ocorrencias):,} linhas) — usadas pela API nas consultas")

    registro = procedencia.registrar_real(
        args.saida, fonte=FONTE, arquivo_bruto=bruto.name,
        linhas=len(dados), periodo=(args.anos[0], args.anos[1]),
    )

    print(f"\n{len(dados):,} linhas escritas em {args.saida.name}")
    print(f"Procedência registrada em {registro.name} (marcada como REAL)")

    print("\nDistribuição do nível de risco:")
    contagem = dados[esquema.COLUNA_ALVO].value_counts()
    for classe in esquema.CLASSES_RISCO:
        n = int(contagem.get(classe, 0))
        print(f"  {classe:<8} {n:>8,}  ({n / len(dados):.1%})")

    print("\nLinhas por tipo de desastre:")
    for grupo, n in dados["grupo_desastre"].value_counts().items():
        print(f"  {grupo:<20} {n:>8,}")

    print("\nA proporção de 'baixo' aqui NÃO é a proporção real de meses sem")
    print("desastre: os negativos foram amostrados para o arquivo caber no")
    print("treino. As probabilidades do modelo devem ser lidas como risco")
    print("relativo entre municípios, não como chance absoluta.")

    print("\nPróximo passo:")
    print("    python treinamento/treinar_modelo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
