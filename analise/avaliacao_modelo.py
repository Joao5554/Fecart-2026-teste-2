"""
Avaliação do modelo, passo a passo — script didático.

Como executar (a partir da raiz do projeto):
    python analise/avaliacao_modelo.py
    python analise/avaliacao_modelo.py --proporcao-teste 0.2
    python analise/avaliacao_modelo.py --rapido        (menos árvores, roda em segundos)

O que este arquivo faz, na ordem:

    BLOCO 1 — Leitura da base
    BLOCO 2 — Tratamento estatístico (nulos, duplicatas, padronização)
    BLOCO 3 — Divisão treino/teste
    BLOCO 4 — Treinamento
    BLOCO 5 — Avaliação e diagnóstico de overfitting/underfitting
    BLOCO 6 — Comparação de proporções (50/50, 70/30, 80/20)
    BLOCO 7 — Divisão aleatória vs divisão temporal

Os blocos 6 e 7 não estavam no roteiro original, mas respondem com números
duas perguntas que o roteiro levanta: "qual proporção usar?" e "o resultado
é confiável?". Em dados com tempo, a segunda importa mais que a primeira.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import caracteristicas, esquema  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
SEMENTE = 42
ANO_CORTE = 2022


def titulo(texto: str) -> None:
    print(f"\n{'=' * 70}\n{texto}\n{'=' * 70}")


# ==========================================================================
# BLOCO 1 — Leitura da base de dados
# ==========================================================================

def ler_dados(caminho: Path) -> pd.DataFrame:
    """Lê o CSV e mostra um retrato geral da base."""
    titulo("BLOCO 1 — LEITURA DA BASE")

    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}", file=sys.stderr)
        print("Rode antes: python dados/preparar_dados.py", file=sys.stderr)
        raise SystemExit(1)

    dados = pd.read_csv(caminho)
    print(f"Arquivo: {caminho.name}")
    print(f"Linhas:  {len(dados):,}")
    print(f"Colunas: {dados.shape[1]}")

    print(f"\nVariável a prever: '{esquema.COLUNA_ALVO}'")
    contagem = dados[esquema.COLUNA_ALVO].value_counts()
    for classe in esquema.CLASSES_RISCO:
        n = int(contagem.get(classe, 0))
        print(f"  {classe:<8} {n:>8,}  ({n / len(dados):>5.1%})")

    # Classe majoritária: é o piso que qualquer modelo precisa superar.
    # Um modelo que só chutasse a classe mais comum já acertaria essa fração.
    maioria = contagem.max() / len(dados)
    print(f"\nChute da classe majoritária acertaria {maioria:.1%}.")
    print("Esse é o piso: acurácia abaixo disso significa modelo inútil.")

    return dados


# ==========================================================================
# BLOCO 2 — Tratamento estatístico
# ==========================================================================

def tratar_dados(dados: pd.DataFrame) -> pd.DataFrame:
    """
    Verifica e corrige os problemas clássicos de uma base: valores nulos,
    linhas duplicadas e escalas incompatíveis.
    """
    titulo("BLOCO 2 — TRATAMENTO ESTATÍSTICO")
    dados = dados.copy()

    # --- 2.1 Valores nulos ------------------------------------------------
    print("2.1  Valores nulos")
    nulos = dados.isna().sum()
    nulos = nulos[nulos > 0]

    if nulos.empty:
        print("     Nenhum valor nulo na base.")
    else:
        for coluna, quantidade in nulos.items():
            print(f"     {coluna}: {quantidade:,} ({quantidade / len(dados):.2%})")

        # Numéricas recebem a MEDIANA, não a média: a mediana não é puxada
        # por valores extremos, e esta base tem muitos (um único desastre pode
        # ter centenas de milhares de afetados).
        for coluna in esquema.COLUNAS_NUMERICAS:
            if coluna in dados.columns and dados[coluna].isna().any():
                dados[coluna] = dados[coluna].fillna(dados[coluna].median())

        # Categóricas recebem a categoria mais frequente (moda).
        for coluna in esquema.COLUNAS_CATEGORICAS:
            if coluna in dados.columns and dados[coluna].isna().any():
                dados[coluna] = dados[coluna].fillna(dados[coluna].mode()[0])

        print(f"     Preenchidos. Restam {int(dados.isna().sum().sum())} nulos.")

    # --- 2.2 Linhas duplicadas -------------------------------------------
    print("\n2.2  Linhas duplicadas")
    # Duplicata aqui não é linha idêntica em tudo: é a mesma combinação de
    # município + ano + mês + tipo de desastre, que deveria ser única.
    antes = len(dados)
    duplicadas = int(dados.duplicated(subset=esquema.CHAVE_LINHA).sum())

    if duplicadas:
        dados = dados.drop_duplicates(subset=esquema.CHAVE_LINHA, keep="first")
        print(f"     {duplicadas:,} removidas ({antes:,} -> {len(dados):,}).")
        print("     Linha repetida daria peso extra àquele caso no treino.")
    else:
        print("     Nenhuma duplicata pela chave "
              f"{' + '.join(esquema.CHAVE_LINHA)}.")

    # --- 2.3 Valores fora da faixa esperada -------------------------------
    print("\n2.3  Valores fora da faixa do contrato de dados")
    problemas = 0
    for coluna in esquema.COLUNAS_NUMERICAS:
        info = esquema.POR_NOME.get(coluna)
        if info is None or info.minimo is None or coluna not in dados.columns:
            continue
        fora = int(
            ((dados[coluna] < info.minimo) | (dados[coluna] > info.maximo)).sum()
        )
        if fora:
            print(f"     {coluna}: {fora:,} fora de [{info.minimo}, {info.maximo}]")
            problemas += 1

    if not problemas:
        print("     Todas as colunas dentro das faixas declaradas.")

    # --- 2.4 Padronização --------------------------------------------------
    print("\n2.4  Padronização (normalização das escalas)")
    print("     NÃO é aplicada aqui, e isso é uma decisão, não um esquecimento.")
    print("     Árvores de decisão dividem por limiares ('chuva > 100?'), então")
    print("     multiplicar uma coluna por 1000 não muda nenhuma divisão — o")
    print("     Random Forest é indiferente à escala.")
    print("     Padronizar é indispensável em modelos que somam coeficientes")
    print("     (regressão logística, SVM, redes neurais). O bloco 5 comprova")
    print("     na prática que aqui não faz diferença.")

    return dados


# ==========================================================================
# BLOCO 3 — Divisão dos dados
# ==========================================================================

def dividir(dados: pd.DataFrame, proporcao_teste: float, temporal: bool = False):
    """
    Separa treino e teste.

    `temporal=False` usa o train_test_split do scikit-learn, sorteando as
    linhas. `temporal=True` corta por ano: passado para treinar, futuro para
    testar. O bloco 7 mostra por que a diferença importa nesta base.
    """
    titulo("BLOCO 3 — DIVISÃO DOS DADOS")

    X, y = caracteristicas.separar_x_y(dados)

    if temporal:
        eh_treino = dados["ano"] < ANO_CORTE
        X_treino, X_teste = X[eh_treino], X[~eh_treino]
        y_treino, y_teste = y[eh_treino], y[~eh_treino]
        print(f"Divisão TEMPORAL no ano {ANO_CORTE}")
        print(f"  treino: {dados.loc[eh_treino, 'ano'].min()}"
              f"–{dados.loc[eh_treino, 'ano'].max()}")
        print(f"  teste:  {dados.loc[~eh_treino, 'ano'].min()}"
              f"–{dados.loc[~eh_treino, 'ano'].max()}")
    else:
        # stratify=y mantém a mesma proporção de baixo/medio/alto dos dois
        # lados. Sem isso, o sorteio pode deixar o teste com poucos casos
        # graves e a métrica vira loteria.
        X_treino, X_teste, y_treino, y_teste = train_test_split(
            X, y,
            test_size=proporcao_teste,
            random_state=SEMENTE,   # deixa o resultado reproduzível
            stratify=y,
        )
        print(f"Divisão ALEATÓRIA — {1 - proporcao_teste:.0%} treino / "
              f"{proporcao_teste:.0%} teste")

    print(f"\n  treino: {len(X_treino):>8,} linhas")
    print(f"  teste:  {len(X_teste):>8,} linhas")

    print("\nProporção das classes (confirma que o split não distorceu):")
    print(f"  {'classe':<10}{'treino':>10}{'teste':>10}")
    for classe in esquema.CLASSES_RISCO:
        print(f"  {classe:<10}{(y_treino == classe).mean():>9.1%}"
              f"{(y_teste == classe).mean():>10.1%}")

    return X_treino, X_teste, y_treino, y_teste


# ==========================================================================
# BLOCO 4 — Treinamento
# ==========================================================================

def treinar(X_treino, y_treino, arvores: int = 100, profundidade: int | None = 20):
    """Treina o Random Forest usando SOMENTE os dados de treino."""
    titulo("BLOCO 4 — TREINAMENTO")

    modelo = caracteristicas.construir_preprocessador()
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline([
        # O pré-processamento entra dentro do modelo. Assim as mesmas
        # transformações do treino são aplicadas na hora de prever, sem risco
        # de alguém esquecer um passo depois.
        ("preparacao", modelo),
        ("floresta", RandomForestClassifier(
            n_estimators=arvores,
            max_depth=profundidade,
            min_samples_leaf=5,
            # Pesos por CUSTO do erro: num sistema de alerta, não avisar um
            # risco alto é muito pior do que um alarme falso.
            class_weight={"baixo": 1.0, "medio": 3.0, "alto": 6.0},
            random_state=SEMENTE,
            n_jobs=-1,
        )),
    ])

    print(f"Algoritmo:      Random Forest ({arvores} árvores)")
    print(f"Profundidade:   {profundidade or 'sem limite'}")
    print(f"Treinando com {len(X_treino):,} linhas...")
    pipeline.fit(X_treino, y_treino)
    print("Concluído.")

    return pipeline


# ==========================================================================
# BLOCO 5 — Avaliação e diagnóstico
# ==========================================================================

def avaliar(modelo, X_treino, y_treino, X_teste, y_teste) -> dict:
    """
    Mede o desempenho e diagnostica overfitting/underfitting.

    A comparação treino x teste é o que revela o problema: um modelo que
    acerta muito no treino e pouco no teste decorou em vez de aprender.
    """
    titulo("BLOCO 5 — AVALIAÇÃO E DIAGNÓSTICO")

    previsao_treino = modelo.predict(X_treino)
    previsao_teste = modelo.predict(X_teste)

    metricas = {
        "acuracia_treino": accuracy_score(y_treino, previsao_treino),
        "acuracia_teste": accuracy_score(y_teste, previsao_teste),
        "balanceada_treino": balanced_accuracy_score(y_treino, previsao_treino),
        "balanceada_teste": balanced_accuracy_score(y_teste, previsao_teste),
        "f1_treino": f1_score(y_treino, previsao_treino, average="macro"),
        "f1_teste": f1_score(y_teste, previsao_teste, average="macro"),
    }

    print("5.1  Desempenho no TESTE (dados que o modelo nunca viu)")
    print(f"     Acurácia ............ {metricas['acuracia_teste']:.2%}")
    print(f"     Acurácia balanceada . {metricas['balanceada_teste']:.2%}")
    print(f"     F1-score (macro) .... {metricas['f1_teste']:.3f}")
    print("\n     A acurácia balanceada é a média do acerto POR CLASSE.")
    print("     Com classes desbalanceadas, ela é o número honesto: a acurácia")
    print("     simples pode ficar alta só acertando a classe mais comum.")

    print("\n5.2  Desempenho por classe")
    print(classification_report(
        y_teste, previsao_teste,
        labels=esquema.CLASSES_RISCO,
        target_names=esquema.CLASSES_RISCO,
        digits=3, zero_division=0,
    ))

    print("5.3  Matriz de confusão (linha = real, coluna = previsto)")
    matriz = confusion_matrix(y_teste, previsao_teste, labels=esquema.CLASSES_RISCO)
    print("            " + "".join(f"{c:>10}" for c in esquema.CLASSES_RISCO))
    for classe, linha in zip(esquema.CLASSES_RISCO, matriz):
        print(f"  real {classe:<6}" + "".join(f"{v:>10,}" for v in linha))

    indice_alto = esquema.CLASSES_RISCO.index("alto")
    total_alto = matriz[indice_alto].sum()
    if total_alto:
        recall = matriz[indice_alto, indice_alto] / total_alto
        perdidos = matriz[indice_alto, esquema.CLASSES_RISCO.index("baixo")]
        print(f"\n     Casos graves identificados: {recall:.1%}")
        print(f"     Graves classificados como BAIXO: {perdidos:,} "
              f"(o erro mais custoso num alerta)")

    # --- Diagnóstico -------------------------------------------------------
    print("\n5.4  Overfitting ou underfitting?")
    print(f"     {'':<22}{'treino':>10}{'teste':>10}{'diferença':>12}")
    for nome, chave in [("Acurácia", "acuracia"),
                        ("Acurácia balanceada", "balanceada"),
                        ("F1 macro", "f1")]:
        treino = metricas[f"{chave}_treino"]
        teste = metricas[f"{chave}_teste"]
        print(f"     {nome:<22}{treino:>9.1%}{teste:>10.1%}{treino - teste:>11.1%}")

    diferenca = metricas["balanceada_treino"] - metricas["balanceada_teste"]
    metricas["diferenca_treino_teste"] = diferenca

    print()
    if diferenca > 0.15:
        metricas["diagnostico"] = "overfitting"
        print("     >> OVERFITTING: o modelo vai muito melhor no treino do que")
        print("        no teste. Ele decorou os exemplos em vez de aprender o")
        print("        padrão. Soluções: limitar a profundidade das árvores,")
        print("        aumentar min_samples_leaf, ou conseguir mais dados.")
    elif metricas["balanceada_teste"] < 0.40:
        metricas["diagnostico"] = "underfitting"
        print("     >> UNDERFITTING: o desempenho é baixo nos DOIS conjuntos.")
        print("        O modelo é simples demais, ou as variáveis disponíveis")
        print("        não explicam o fenômeno. Soluções: mais variáveis")
        print("        (aqui, dados de chuva) ou um modelo mais flexível.")
    else:
        metricas["diagnostico"] = "equilibrado"
        print("     >> EQUILIBRADO: a diferença entre treino e teste é pequena.")
        print("        O modelo generaliza — o que ele acerta no teste, acerta")
        print("        por ter aprendido, não por ter decorado.")

    return metricas


# ==========================================================================
# BLOCO 6 — Comparação de proporções de divisão
# ==========================================================================

def comparar_proporcoes(dados: pd.DataFrame, arvores: int) -> pd.DataFrame:
    """
    Roda o mesmo experimento com 50/50, 70/30 e 80/20.

    Responde com números a pergunta "qual proporção devo usar?", em vez de
    seguir uma regra decorada.
    """
    titulo("BLOCO 6 — 50/50 vs 70/30 vs 80/20")
    print("Mesmo modelo, mesma semente; muda só quanto vai para o treino.\n")

    X, y = caracteristicas.separar_x_y(dados)
    linhas = []

    for proporcao in (0.5, 0.3, 0.2):
        X_treino, X_teste, y_treino, y_teste = train_test_split(
            X, y, test_size=proporcao, random_state=SEMENTE, stratify=y
        )
        modelo = treinar_silencioso(X_treino, y_treino, arvores)
        previsao = modelo.predict(X_teste)

        linhas.append({
            "treino": f"{1 - proporcao:.0%}",
            "teste": f"{proporcao:.0%}",
            "linhas_treino": len(X_treino),
            "linhas_teste": len(X_teste),
            "balanceada": balanced_accuracy_score(y_teste, previsao),
            "f1_macro": f1_score(y_teste, previsao, average="macro"),
        })

    tabela = pd.DataFrame(linhas)
    print(f"{'treino':>8}{'teste':>8}{'linhas treino':>16}"
          f"{'balanceada':>13}{'F1 macro':>11}")
    for _, linha in tabela.iterrows():
        print(f"{linha['treino']:>8}{linha['teste']:>8}"
              f"{linha['linhas_treino']:>16,}"
              f"{linha['balanceada']:>12.1%}{linha['f1_macro']:>11.3f}")

    diferenca = tabela["balanceada"].max() - tabela["balanceada"].min()
    print(f"\nDiferença entre a melhor e a pior: {diferenca:.1%}")
    if diferenca < 0.02:
        print("Praticamente nula. Com quase 200 mil linhas, metade da base já")
        print("é exemplo de sobra — a proporção deixa de ser decisiva.")
        print("Em bases pequenas (centenas de linhas), 80/20 faz diferença real.")
    else:
        print("Diferença relevante: vale usar a proporção com mais treino.")

    return tabela


def treinar_silencioso(X_treino, y_treino, arvores: int):
    """Mesmo modelo do bloco 4, sem imprimir nada (usado nas comparações)."""
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("preparacao", caracteristicas.construir_preprocessador()),
        ("floresta", RandomForestClassifier(
            n_estimators=arvores, max_depth=20, min_samples_leaf=5,
            class_weight={"baixo": 1.0, "medio": 3.0, "alto": 6.0},
            random_state=SEMENTE, n_jobs=-1,
        )),
    ]).fit(X_treino, y_treino)


# ==========================================================================
# BLOCO 7 — Divisão aleatória vs temporal
# ==========================================================================

def comparar_aleatorio_e_temporal(dados: pd.DataFrame, arvores: int) -> dict:
    """
    A comparação mais importante desta base.

    O `train_test_split` sorteia linhas ao acaso. Em dados com tempo, isso
    coloca meses de 2024 no treino e meses de 2015 no teste — o modelo usa o
    futuro para prever o passado. O número sai mais bonito e não se sustenta.
    """
    titulo("BLOCO 7 — DIVISÃO ALEATÓRIA vs TEMPORAL")

    X, y = caracteristicas.separar_x_y(dados)
    resultados = {}

    # Aleatória, com a mesma quantidade de teste da temporal, para a
    # comparação não ser afetada pelo tamanho do conjunto.
    eh_treino = dados["ano"] < ANO_CORTE
    proporcao_equivalente = float((~eh_treino).mean())

    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=proporcao_equivalente, random_state=SEMENTE, stratify=y
    )
    modelo = treinar_silencioso(X_treino, y_treino, arvores)
    previsao = modelo.predict(X_teste)
    resultados["aleatoria"] = {
        "balanceada": balanced_accuracy_score(y_teste, previsao),
        "f1_macro": f1_score(y_teste, previsao, average="macro"),
    }

    # Temporal: treina no passado, testa no futuro.
    modelo = treinar_silencioso(X[eh_treino], y[eh_treino], arvores)
    previsao = modelo.predict(X[~eh_treino])
    resultados["temporal"] = {
        "balanceada": balanced_accuracy_score(y[~eh_treino], previsao),
        "f1_macro": f1_score(y[~eh_treino], previsao, average="macro"),
    }

    print(f"Ambas com {proporcao_equivalente:.0%} dos dados no teste.\n")
    print(f"{'divisão':<14}{'balanceada':>13}{'F1 macro':>11}")
    for nome in ("aleatoria", "temporal"):
        r = resultados[nome]
        print(f"{nome:<14}{r['balanceada']:>12.1%}{r['f1_macro']:>11.3f}")

    inflacao = (resultados["aleatoria"]["balanceada"]
                - resultados["temporal"]["balanceada"])
    resultados["inflacao"] = inflacao

    print(f"\nA divisão aleatória parece {inflacao:.1%} melhor.")
    if inflacao > 0.02:
        print("Essa diferença é ILUSÃO, não desempenho:")
        print("  - o modelo treinou com meses de 2024 e foi testado em 2015;")
        print("  - o mesmo município aparece nos dois lados, em meses vizinhos;")
        print("  - na vida real só existe o passado para treinar.")
        print("\nO número honesto para a apresentação é o da divisão TEMPORAL.")
    else:
        print("Diferença pequena — neste caso as duas divisões concordam.")

    return resultados


# ==========================================================================
# Execução
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Avaliação didática do modelo, passo a passo."
    )
    parser.add_argument("--dados", type=Path, default=ARQUIVO_DADOS)
    parser.add_argument("--proporcao-teste", type=float, default=0.5,
                        help="fração para teste no bloco 3 (padrão: 0.5)")
    parser.add_argument("--temporal", action="store_true",
                        help="usa divisão temporal no bloco 3")
    parser.add_argument("--rapido", action="store_true",
                        help="30 árvores em vez de 100; roda em segundos")
    parser.add_argument("--sem-comparacoes", action="store_true",
                        help="pula os blocos 6 e 7")
    argumentos = parser.parse_args()

    arvores = 30 if argumentos.rapido else 100

    dados = ler_dados(argumentos.dados)
    dados = tratar_dados(dados)

    X_treino, X_teste, y_treino, y_teste = dividir(
        dados, argumentos.proporcao_teste, argumentos.temporal
    )
    modelo = treinar(X_treino, y_treino, arvores)
    avaliar(modelo, X_treino, y_treino, X_teste, y_teste)

    if not argumentos.sem_comparacoes:
        comparar_proporcoes(dados, arvores)
        comparar_aleatorio_e_temporal(dados, arvores)

    titulo("RESUMO")
    print("1. A base foi lida e verificada (nulos, duplicatas, faixas).")
    print("2. Padronizar não é necessário para Random Forest — só para")
    print("   modelos que somam coeficientes.")
    print("3. Com ~187 mil linhas, 50/50 e 80/20 dão quase o mesmo resultado.")
    print("4. O que muda o número de verdade é a divisão ser temporal ou")
    print("   aleatória. Nesta base, a aleatória infla o desempenho.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
