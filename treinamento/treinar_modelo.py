"""
Treinamento do modelo de previsão de risco de desastres naturais.

Como executar (a partir da raiz do projeto):
    python treinamento/treinar_modelo.py
    python treinamento/treinar_modelo.py --dados dados/dados.csv --arvores 300
    python treinamento/treinar_modelo.py --sem-validacao-cruzada   (mais rápido)

O que o script faz:
    1. Carrega e valida o CSV contra o contrato de src/esquema.py
    2. Separa treino e teste, mantendo a proporção das classes
    3. Monta um Pipeline: imputação + one-hot + Random Forest
    4. Avalia: acurácia, precisão/recall/F1 por classe, matriz de confusão
    5. Faz validação cruzada, para saber se o resultado é estável
    6. Mostra quais variáveis mais pesaram na decisão
    7. Salva modelo/modelo.pkl e modelo/metadados.json

O Pipeline inteiro é salvo (não só o Random Forest). Assim o backend aplica
exatamente as mesmas transformações usadas no treino.
"""

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import caracteristicas, esquema, procedencia  # noqa: E402
from src.carregar import ErroDeDados, carregar_dados, resumir  # noqa: E402


RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_DADOS_PADRAO = RAIZ / "dados" / "dados.csv"
PASTA_MODELO = RAIZ / "modelo"
ARQUIVO_MODELO = PASTA_MODELO / "modelo.pkl"
ARQUIVO_METADADOS = PASTA_MODELO / "metadados.json"


def titulo(texto: str) -> None:
    print(f"\n{'=' * 66}\n{texto}\n{'=' * 66}")


def construir_modelo(arvores: int, profundidade: int | None, semente: int) -> Pipeline:
    """Monta o pipeline completo: pré-processamento + classificador."""
    floresta = RandomForestClassifier(
        n_estimators=arvores,
        max_depth=profundidade,
        # Sem isso, o modelo aprende a chutar sempre "baixo" (62% dos casos) e
        # ainda assim exibe uma acurácia alta. Num sistema de alerta, errar um
        # risco "alto" custa muito mais caro do que errar um "baixo".
        class_weight="balanced",
        min_samples_leaf=2,
        n_jobs=-1,
        random_state=semente,
    )

    return Pipeline([
        ("preparacao", caracteristicas.construir_preprocessador()),
        ("floresta", floresta),
    ])


def avaliar(modelo: Pipeline, X_teste: pd.DataFrame, y_teste: pd.Series) -> dict:
    """Avalia o modelo no conjunto de teste e imprime o relatório."""
    previsoes = modelo.predict(X_teste)

    acuracia = accuracy_score(y_teste, previsoes)
    acuracia_balanceada = balanced_accuracy_score(y_teste, previsoes)
    f1_macro = f1_score(y_teste, previsoes, average="macro")

    titulo("DESEMPENHO NO CONJUNTO DE TESTE")
    print(f"Acurácia:             {acuracia:.2%}")
    print(f"Acurácia balanceada:  {acuracia_balanceada:.2%}  "
          f"(média do acerto por classe — o número honesto quando as classes "
          f"são desbalanceadas)")
    print(f"F1 macro:             {f1_macro:.2%}")

    print("\nDesempenho por nível de risco:")
    print(classification_report(
        y_teste, previsoes,
        labels=esquema.CLASSES_RISCO,
        target_names=esquema.CLASSES_RISCO,
        digits=3,
        zero_division=0,
    ))

    print("Matriz de confusão (linha = real, coluna = previsto):")
    matriz = confusion_matrix(y_teste, previsoes, labels=esquema.CLASSES_RISCO)
    cabecalho = "            " + "".join(f"{c:>10}" for c in esquema.CLASSES_RISCO)
    print(cabecalho)
    for classe, linha in zip(esquema.CLASSES_RISCO, matriz):
        print(f"  real {classe:<6}" + "".join(f"{v:>10,}" for v in linha))

    # Num sistema de alerta, este é o número que mais importa: de todos os
    # casos que eram de fato risco alto, quantos o modelo pegou?
    indice_alto = esquema.CLASSES_RISCO.index("alto")
    total_alto = matriz[indice_alto].sum()
    if total_alto:
        recall_alto = matriz[indice_alto, indice_alto] / total_alto
        perdidos_como_baixo = matriz[indice_alto, esquema.CLASSES_RISCO.index("baixo")]
        print(f"\n>> O modelo identificou {recall_alto:.1%} dos casos de risco ALTO.")
        if perdidos_como_baixo:
            print(f">> Atenção: {perdidos_como_baixo:,} caso(s) de risco alto foram "
                  f"classificados como BAIXO. Esse é o erro mais grave possível "
                  f"num sistema de alerta.")

    return {
        "acuracia": float(acuracia),
        "acuracia_balanceada": float(acuracia_balanceada),
        "f1_macro": float(f1_macro),
        "matriz_confusao": matriz.tolist(),
        "relatorio_por_classe": classification_report(
            y_teste, previsoes,
            labels=esquema.CLASSES_RISCO,
            target_names=esquema.CLASSES_RISCO,
            output_dict=True,
            zero_division=0,
        ),
    }


def validar_cruzado(modelo: Pipeline, X: pd.DataFrame, y: pd.Series,
                    particoes: int, semente: int) -> dict:
    """Repete o treino em várias divisões dos dados.

    Uma acurácia boa em uma única divisão pode ser sorte. Se o desvio-padrão
    entre as partições for alto, o resultado não é confiável.
    """
    titulo(f"VALIDAÇÃO CRUZADA ({particoes} partições)")
    print("Treinando em várias divisões dos dados... (pode demorar)")

    divisor = StratifiedKFold(n_splits=particoes, shuffle=True, random_state=semente)
    notas = cross_val_score(
        modelo, X, y, cv=divisor, scoring="balanced_accuracy", n_jobs=-1
    )

    print(f"\nAcurácia balanceada por partição: "
          f"{', '.join(f'{n:.1%}' for n in notas)}")
    print(f"Média: {notas.mean():.2%}  (desvio-padrão: {notas.std():.2%})")

    if notas.std() > 0.05:
        print("\n[aviso] Variação alta entre as partições. O desempenho depende "
              "muito de quais linhas caem no treino — sinal de que faltam dados.")
    else:
        print("\nVariação baixa entre as partições: o resultado é estável.")

    return {
        "particoes": particoes,
        "notas": [float(n) for n in notas],
        "media": float(notas.mean()),
        "desvio_padrao": float(notas.std()),
    }


def mostrar_importancias(modelo: Pipeline, quantidade: int = 15) -> dict:
    """Mostra quais variáveis mais influenciaram as decisões do modelo."""
    titulo("VARIÁVEIS MAIS IMPORTANTES")

    preparacao = modelo.named_steps["preparacao"]
    floresta = modelo.named_steps["floresta"]

    nomes = list(preparacao.get_feature_names_out())
    agregadas = caracteristicas.importancia_por_coluna_original(
        nomes, floresta.feature_importances_
    )

    print(f"{'variável':<38} {'peso':>8}")
    print("-" * 48)
    for nome, peso in list(agregadas.items())[:quantidade]:
        info = esquema.POR_NOME.get(nome)
        barra = "#" * int(peso * 120)
        print(f"{nome:<38} {peso:>7.1%}  {barra}")
        if info and info.descricao:
            print(f"    {info.descricao}")

    return agregadas


def salvar(modelo: Pipeline, dados: pd.DataFrame, metricas: dict,
           cruzada: dict | None, importancias: dict, argumentos) -> None:
    """Salva o modelo e um arquivo de metadados ao lado dele."""
    PASTA_MODELO.mkdir(parents=True, exist_ok=True)
    # Sem compressão uma floresta de 300 árvores passa de 100 MB. compress=3
    # reduz para uma fração disso e custa poucos segundos a mais no carregamento.
    joblib.dump(modelo, ARQUIVO_MODELO, compress=3)

    origem = procedencia.identificar(argumentos.dados)

    metadados = {
        "treinado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Assinatura do contrato de dados. A API recusa carregar um modelo cuja
        # assinatura não bata com a do código atual (ver src/esquema.assinatura).
        "versao_esquema": esquema.VERSAO_ESQUEMA,
        "assinatura_esquema": esquema.assinatura(),
        "arquivo_dados": str(argumentos.dados),
        # Identidade exata da base usada. Permite provar, meses depois, com
        # quais dados este modelo foi treinado.
        "origem_dados": origem["origem"],
        "hash_dados_sha256": origem["hash_sha256"],
        "aviso_dados": origem.get("aviso"),
        "linhas_totais": int(len(dados)),
        "proporcao_teste": argumentos.proporcao_teste,
        "classes": esquema.CLASSES_RISCO,
        "distribuicao_classes": {
            str(k): int(v)
            for k, v in dados[esquema.COLUNA_ALVO].value_counts().items()
        },
        "grupos_cobrade": sorted(dados["cobrade_grupo"].unique().tolist()),
        "municipios": int(dados["codigo_ibge"].nunique()),
        "periodo": {
            "ano_inicial": int(dados["ano"].min()),
            "ano_final": int(dados["ano"].max()),
        },
        "colunas_entrada": {
            "numericas": esquema.COLUNAS_MODELO_NUMERICAS,
            "categoricas": esquema.COLUNAS_MODELO_CATEGORICAS,
        },
        "hiperparametros": {
            "n_estimators": argumentos.arvores,
            "max_depth": argumentos.profundidade,
            "class_weight": "balanced",
            "min_samples_leaf": 2,
            "random_state": argumentos.semente,
        },
        "metricas": metricas,
        "validacao_cruzada": cruzada,
        "importancia_variaveis": importancias,
        "versoes": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }

    ARQUIVO_METADADOS.write_text(
        json.dumps(metadados, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    tamanho_mb = ARQUIVO_MODELO.stat().st_size / 1024 / 1024
    titulo("ARQUIVOS SALVOS")
    print(f"Modelo:     {ARQUIVO_MODELO}  ({tamanho_mb:.1f} MB)")
    print(f"Metadados:  {ARQUIVO_METADADOS}")
    print(f"Origem dos dados: {origem['origem'].upper()}  "
          f"(sha256 {origem['hash_sha256'][:12]}...)")

    if origem["origem"] == procedencia.SINTETICO:
        print("\n" + "!" * 66)
        print(procedencia.AVISO_SINTETICO)
        print("!" * 66)
    print("\nPara servir as previsões, rode:")
    print("    uvicorn backend.app:app --reload")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Treina o modelo de risco de desastres naturais."
    )
    parser.add_argument("--dados", type=Path, default=ARQUIVO_DADOS_PADRAO,
                        help="caminho do CSV de treino")
    parser.add_argument("--arvores", type=int, default=300,
                        help="número de árvores da floresta (padrão: 300)")
    parser.add_argument("--profundidade", type=int, default=None,
                        help="profundidade máxima das árvores (padrão: sem limite)")
    parser.add_argument("--proporcao-teste", type=float, default=0.2,
                        help="fração dos dados reservada para teste (padrão: 0.2)")
    parser.add_argument("--particoes", type=int, default=5,
                        help="partições da validação cruzada (padrão: 5)")
    parser.add_argument("--sem-validacao-cruzada", action="store_true",
                        help="pula a validação cruzada (treino bem mais rápido)")
    parser.add_argument("--semente", type=int, default=42,
                        help="semente aleatória, para o treino ser reproduzível")
    argumentos = parser.parse_args()

    titulo("CARREGANDO OS DADOS")
    try:
        dados = carregar_dados(argumentos.dados)
    except ErroDeDados as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    resumir(dados)

    titulo("PREPARANDO AS FEATURES")
    X, y = caracteristicas.separar_x_y(dados)
    print(f"{X.shape[1]} variáveis de entrada, {len(X):,} exemplos")
    print(f"  {len(esquema.COLUNAS_MODELO_NUMERICAS)} numéricas "
          f"(incluindo {len(esquema.COLUNAS_DERIVADAS)} calculadas)")
    print(f"  {len(esquema.COLUNAS_MODELO_CATEGORICAS)} categóricas "
          f"(viram colunas separadas no one-hot)")

    # stratify mantém a mesma proporção de baixo/medio/alto nos dois lados.
    # Sem isso, o conjunto de teste pode acabar com poucos casos de risco alto.
    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y,
        test_size=argumentos.proporcao_teste,
        random_state=argumentos.semente,
        stratify=y,
    )
    print(f"\nTreino: {len(X_treino):,} linhas | Teste: {len(X_teste):,} linhas")

    titulo("TREINANDO O RANDOM FOREST")
    print(f"Árvores: {argumentos.arvores} | "
          f"Profundidade máxima: {argumentos.profundidade or 'sem limite'}")
    modelo = construir_modelo(
        argumentos.arvores, argumentos.profundidade, argumentos.semente
    )
    modelo.fit(X_treino, y_treino)
    print("Treinamento concluído.")

    metricas = avaliar(modelo, X_teste, y_teste)

    cruzada = None
    if not argumentos.sem_validacao_cruzada:
        cruzada = validar_cruzado(
            construir_modelo(
                argumentos.arvores, argumentos.profundidade, argumentos.semente
            ),
            X, y, argumentos.particoes, argumentos.semente,
        )

    importancias = mostrar_importancias(modelo)

    salvar(modelo, dados, metricas, cruzada, importancias, argumentos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
