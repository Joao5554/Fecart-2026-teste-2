"""
Treinamento do modelo Random Forest de risco de desastres naturais.

Como executar (a partir da raiz do projeto):
    python treinamento/treinar_modelo.py

O script:
  1. Escolhe a base de dados (a real, se existir; senão a sintética).
  2. Valida os dados contra o esquema do projeto.
  3. Treina uma Pipeline (pré-processamento + Random Forest).
  4. Avalia com validação cruzada e em um conjunto de teste separado.
  5. Salva modelos/modelo.pkl e modelos/modelo_metadados.json.

O modelo roda 100% localmente: nenhum dado sai da máquina e nenhuma
chamada de rede é feita, nem no treino nem na hora de prever.
"""

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# Permite executar este arquivo diretamente (python treinamento/treinar_modelo.py)
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

from treinamento.esquema import (
    ARQUIVO_METADADOS,
    ARQUIVO_MODELO,
    CLASSES,
    COLUNA_ALVO,
    DIR_MODELOS,
    NOMES_COLUNAS,
    caminho_dados,
)
from treinamento.preprocessamento import (
    criar_preprocessador,
    separar_x_y,
    validar_dados,
)

# Versão do formato do modelo. Aumente ao mudar o esquema de entrada:
# a API recusa modelos de versão diferente, evitando previsões silenciosamente
# erradas depois de um `git pull`.
VERSAO_MODELO = "1.0.0"

SEMENTE = 42
PROPORCAO_TESTE = 0.2

# max_depth e min_samples_leaf limitam o tamanho das árvores. Além de reduzir
# o sobreajuste, mantêm o modelo.pkl pequeno o suficiente para ser gerado e
# carregado rápido em qualquer computador da equipe.
PARAMETROS_FLORESTA = {
    "n_estimators": 200,
    "max_depth": 16,
    "min_samples_leaf": 3,
    "max_features": "sqrt",
    "class_weight": "balanced_subsample",
    "n_jobs": -1,
    "random_state": SEMENTE,
}


def _hash_arquivo(caminho: Path) -> str:
    """SHA-256 do arquivo de dados, registrado nos metadados do modelo."""
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(65536), b""):
            digest.update(bloco)
    return digest.hexdigest()


def carregar_dados() -> tuple[pd.DataFrame, Path, str]:
    """Carrega a base de dados, gerando a sintética se ainda não existir."""
    caminho, origem = caminho_dados()

    if not caminho.exists():
        print("Base de exemplo não encontrada. Gerando dados sintéticos...")
        from treinamento.gerar_dados_exemplo import main as gerar_exemplo

        gerar_exemplo()
        print()
        caminho, origem = caminho_dados()

    dados = pd.read_csv(caminho)
    return dados, caminho, origem


def criar_modelo() -> Pipeline:
    """Pipeline completa: pré-processamento + Random Forest, num objeto só."""
    return Pipeline([
        ("preprocessamento", criar_preprocessador()),
        ("floresta", RandomForestClassifier(**PARAMETROS_FLORESTA)),
    ])


def importancia_variaveis(modelo: Pipeline) -> dict[str, float]:
    """
    Importância de cada variável ORIGINAL do esquema.

    O one-hot encoding quebra uma coluna categórica em várias; aqui as
    importâncias são somadas de volta para a coluna de origem, o que
    torna o resultado legível para apresentação.
    """
    preprocessador = modelo.named_steps["preprocessamento"]
    floresta = modelo.named_steps["floresta"]

    nomes_transformados = preprocessador.get_feature_names_out()
    importancias = floresta.feature_importances_

    total_por_coluna: dict[str, float] = {nome: 0.0 for nome in NOMES_COLUNAS}
    for nome_transformado, valor in zip(nomes_transformados, importancias):
        # Colunas numéricas mantêm o nome; categóricas viram "coluna_categoria".
        origem = next(
            (
                coluna
                for coluna in NOMES_COLUNAS
                if nome_transformado == coluna
                or nome_transformado.startswith(f"{coluna}_")
            ),
            None,
        )
        if origem is not None:
            total_por_coluna[origem] += float(valor)

    return dict(
        sorted(total_por_coluna.items(), key=lambda item: item[1], reverse=True)
    )


def main() -> None:
    print("=" * 68)
    print("TREINAMENTO — Modelo de risco de desastres naturais (Fecart 2026)")
    print("=" * 68)

    # 1. Dados -------------------------------------------------------------
    dados, caminho, origem = carregar_dados()
    print(f"\n[1/5] Dados carregados de: {caminho.relative_to(caminho.parents[2])}")
    print(f"      Origem: {origem.upper()}  |  {len(dados)} linhas, {dados.shape[1]} colunas")

    if origem == "sintetico":
        print(
            "      ATENÇÃO: base SINTÉTICA (dados fictícios). As métricas abaixo\n"
            "      servem para validar o pipeline, não para conclusões reais."
        )

    print("\n[2/5] Validando os dados contra o esquema...")
    validar_dados(dados, exigir_alvo=True)
    X, y = separar_x_y(dados)
    print(f"      OK — {len(NOMES_COLUNAS)} variáveis de entrada, alvo '{COLUNA_ALVO}'")
    print("      Distribuição das classes:")
    for classe, quantidade in y.value_counts().items():
        print(f"        {classe:<20} {quantidade:>5}  ({quantidade / len(y):.1%})")

    # 2. Separação treino/teste -------------------------------------------
    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=PROPORCAO_TESTE, random_state=SEMENTE, stratify=y
    )
    print(
        f"\n[3/5] Separação: {len(X_treino)} para treino, {len(X_teste)} para teste"
    )

    # 3. Validação cruzada -------------------------------------------------
    modelo = criar_modelo()
    particoes = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEMENTE)
    print("      Rodando validação cruzada (5 partições)...")
    escores_cv = cross_val_score(
        modelo, X_treino, y_treino, cv=particoes, scoring="f1_macro", n_jobs=-1
    )
    print(
        f"      F1-macro na validação cruzada: "
        f"{escores_cv.mean():.3f} (+/- {escores_cv.std():.3f})"
    )

    # 4. Treino final e avaliação -----------------------------------------
    print("\n[4/5] Treinando o Random Forest com todos os dados de treino...")
    modelo.fit(X_treino, y_treino)

    previsoes = modelo.predict(X_teste)
    acuracia = accuracy_score(y_teste, previsoes)
    acuracia_balanceada = balanced_accuracy_score(y_teste, previsoes)
    f1_macro = f1_score(y_teste, previsoes, average="macro")

    print(f"\n      Acurácia .................. {acuracia:.2%}")
    print(f"      Acurácia balanceada ....... {acuracia_balanceada:.2%}")
    print(f"      F1-macro .................. {f1_macro:.3f}")

    print("\n      Relatório por classe:")
    relatorio_texto = classification_report(y_teste, previsoes, zero_division=0)
    for linha in relatorio_texto.splitlines():
        print(f"      {linha}")

    rotulos = sorted(y.unique())
    matriz = confusion_matrix(y_teste, previsoes, labels=rotulos)
    print("      Matriz de confusão (linhas = real, colunas = previsto):")
    print(f"      {'':<20}" + "".join(f"{r[:8]:>10}" for r in rotulos))
    for rotulo, linha in zip(rotulos, matriz):
        print(f"      {rotulo:<20}" + "".join(f"{v:>10}" for v in linha))

    importancias = importancia_variaveis(modelo)
    print("\n      Variáveis mais influentes:")
    for nome, valor in list(importancias.items())[:8]:
        barra = "#" * int(valor * 60)
        print(f"        {nome:<32} {valor:.3f}  {barra}")

    # 5. Salvamento --------------------------------------------------------
    DIR_MODELOS.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, ARQUIVO_MODELO)

    metadados = {
        "versao_modelo": VERSAO_MODELO,
        "treinado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origem_dados": origem,
        "arquivo_dados": caminho.name,
        "hash_dados_sha256": _hash_arquivo(caminho),
        "n_amostras": int(len(dados)),
        "n_treino": int(len(X_treino)),
        "n_teste": int(len(X_teste)),
        "algoritmo": "RandomForestClassifier",
        "parametros": {
            chave: valor
            for chave, valor in PARAMETROS_FLORESTA.items()
            if chave != "n_jobs"
        },
        "colunas_entrada": list(NOMES_COLUNAS),
        "coluna_alvo": COLUNA_ALVO,
        "classes": sorted(str(c) for c in modelo.classes_),
        "classes_esperadas_esquema": list(CLASSES),
        "metricas": {
            "acuracia": round(float(acuracia), 4),
            "acuracia_balanceada": round(float(acuracia_balanceada), 4),
            "f1_macro": round(float(f1_macro), 4),
            "f1_macro_cv_media": round(float(escores_cv.mean()), 4),
            "f1_macro_cv_desvio": round(float(escores_cv.std()), 4),
        },
        "importancia_variaveis": {
            nome: round(valor, 4) for nome, valor in importancias.items()
        },
        "ambiente": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "joblib": joblib.__version__,
        },
    }

    with open(ARQUIVO_METADADOS, "w", encoding="utf-8") as arquivo:
        json.dump(metadados, arquivo, ensure_ascii=False, indent=2)

    tamanho_mb = ARQUIVO_MODELO.stat().st_size / (1024 * 1024)
    print(f"\n[5/5] Modelo salvo em: modelos/{ARQUIVO_MODELO.name} ({tamanho_mb:.1f} MB)")
    print(f"      Metadados salvos em: modelos/{ARQUIVO_METADADOS.name}")
    print("\nPróximo passo: subir a API com")
    print("    uvicorn backend.app:app --reload")


if __name__ == "__main__":
    main()
