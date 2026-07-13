"""
Treinamento do modelo Random Forest.

Como executar (a partir da raiz do projeto):
    python treinamento/treinar_modelo.py

O script lê os dados, treina o modelo e salva o arquivo modelo.pkl.
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

# Caminhos relativos à raiz do projeto
RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
ARQUIVO_MODELO = RAIZ / "modelo.pkl"

# TODO: ajustar para os nomes reais das colunas do dataset
COLUNA_ALVO = "alvo"


def main():
    # 1. Ler os dados
    dados = pd.read_csv(ARQUIVO_DADOS)
    print(f"Dados carregados: {dados.shape[0]} linhas, {dados.shape[1]} colunas")

    X = dados.drop(columns=[COLUNA_ALVO])
    y = dados[COLUNA_ALVO]

    # 2. Separar treino e teste
    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # 3. Treinar o Random Forest
    modelo = RandomForestClassifier(n_estimators=100, random_state=42)
    modelo.fit(X_treino, y_treino)

    # 4. Avaliar
    previsoes = modelo.predict(X_teste)
    acuracia = accuracy_score(y_teste, previsoes)
    print(f"Acurácia no conjunto de teste: {acuracia:.2%}")

    # 5. Salvar o modelo
    joblib.dump(modelo, ARQUIVO_MODELO)
    print(f"Modelo salvo em: {ARQUIVO_MODELO}")


if __name__ == "__main__":
    main()
