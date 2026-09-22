"""
De onde vem a diferença entre validação aleatória e temporal?

O experimento anterior mostrou que a aleatória reporta ~9 pontos a mais que
a temporal, e descartou a explicação mais citada: o modelo NÃO está decorando
a identidade do município (blocos por município dão praticamente o mesmo
resultado que a divisão aleatória).

Sobra a hipótese de **deriva**: a base muda com o tempo. A proporção de meses
com ocorrência registrada sobe ao longo dos anos, por aumento real de eventos
e por melhora da notificação. Numa divisão aleatória o modelo vê linhas de
2024 enquanto prevê 2015 — ou seja, já conhece a "época". Na divisão temporal
ele precisa extrapolar para um período com taxa diferente.

Como este script testa isso
---------------------------
Se a deriva for a causa, a diferença deve **encolher** quando as duas
estratégias são aplicadas dentro de um período curto, em que a taxa quase
não muda. É o que se mede aqui.

Não altera nada do projeto.

    python experimentos/diagnosticar_diferenca.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedKFold

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import caracteristicas, esquema  # noqa: E402
from treinamento.treinar_modelo import construir_modelo  # noqa: E402

SEMENTE = 42
ARVORES = 40


def titulo(texto):
    print(f"\n{'=' * 72}\n{texto}\n{'=' * 72}")


def aleatoria(X, y, particoes=4):
    divisor = StratifiedKFold(n_splits=particoes, shuffle=True, random_state=SEMENTE)
    notas = []
    for treino, teste in divisor.split(X, y):
        m = construir_modelo(ARVORES, 16, SEMENTE, 5).fit(X.iloc[treino], y.iloc[treino])
        notas.append(balanced_accuracy_score(y.iloc[teste], m.predict(X.iloc[teste])))
    return float(np.mean(notas))


def temporal(X, y, anos):
    """Treina em todos os anos menos o último do bloco; testa no último."""
    disponiveis = sorted(anos.unique())
    ultimo = disponiveis[-1]
    treino = (anos < ultimo).to_numpy()
    teste = (anos == ultimo).to_numpy()
    if treino.sum() == 0 or teste.sum() == 0:
        return None
    m = construir_modelo(ARVORES, 16, SEMENTE, 5).fit(X[treino], y[treino])
    return float(balanced_accuracy_score(y[teste], m.predict(X[teste])))


def main() -> int:
    dados = pd.read_csv(RAIZ / "dados" / "dados.csv")
    X, y = caracteristicas.separar_x_y(dados)

    titulo("A BASE MUDA COM O TEMPO?")
    por_ano = dados.assign(positivo=(dados[esquema.COLUNA_ALVO] != "baixo")).groupby("ano")
    taxas = por_ano["positivo"].mean()
    print("  taxa de meses com ocorrência registrada, por ano:")
    for ano in sorted(taxas.index):
        barra = "#" * int(taxas[ano] * 90)
        print(f"    {ano}  {taxas[ano]:>6.1%}  {barra}")

    variacao = taxas.max() - taxas.min()
    print(f"\n  variação ao longo do período: {variacao:.1%}")
    print("  Se fosse estável, aleatória e temporal tenderiam a concordar.")

    titulo("MESMO ANO DE TESTE, MESMO TAMANHO DE TREINO")
    print("  Comparar 'aleatória' com 'temporal' de qualquer jeito é injusto:")
    print("  a temporal costuma treinar com menos linhas, e parte da queda vem")
    print("  daí, não da ordem do tempo. Aqui as duas recebem EXATAMENTE o mesmo")
    print("  número de linhas de treino e são avaliadas no MESMO ano.\n")
    print("  A única diferença é de onde vêm essas linhas:")
    print("    passado  -> só de anos anteriores ao ano testado")
    print("    sorteado -> de qualquer ano, inclusive posteriores\n")

    print(f"  {'ano testado':<14}{'linhas treino':>15}{'só passado':>13}"
          f"{'sorteado':>11}{'diferença':>12}")
    print("  " + "-" * 66)

    rng = np.random.default_rng(SEMENTE)
    diferencas = []

    for ano_alvo in (2018, 2020, 2022, 2024):
        teste = (dados["ano"] == ano_alvo).to_numpy()
        passado = (dados["ano"] < ano_alvo).to_numpy()
        outros = (dados["ano"] != ano_alvo).to_numpy()

        if teste.sum() < 500 or passado.sum() < 5000:
            continue

        # O tamanho do treino é o do conjunto "só passado"; o sorteado recebe
        # a mesma quantidade, tirada de todos os anos menos o testado.
        n = int(passado.sum())
        indices_passado = np.flatnonzero(passado)
        indices_sorteado = rng.choice(np.flatnonzero(outros), size=n, replace=False)

        notas = {}
        for rotulo, indices in (("passado", indices_passado),
                                ("sorteado", indices_sorteado)):
            m = construir_modelo(ARVORES, 16, SEMENTE, 5)
            m.fit(X.iloc[indices], y.iloc[indices])
            notas[rotulo] = balanced_accuracy_score(
                y[teste], m.predict(X[teste])
            )

        diferenca = notas["sorteado"] - notas["passado"]
        diferencas.append(diferenca)
        print(f"  {ano_alvo:<14}{n:>15,}{notas['passado']:>12.1%}"
              f"{notas['sorteado']:>11.1%}{diferenca:>+11.1%}")

    titulo("LEITURA")
    if diferencas:
        media = float(np.mean(diferencas))
        print(f"  Vantagem média de poder ver o futuro: {media:+.1%}")
        print()
        if media > 0.02:
            print("  Com o mesmo tamanho de treino e o mesmo ano de teste, o")
            print("  modelo que enxerga anos POSTERIORES vai melhor. Essa")
            print("  vantagem é exatamente o que a validação aleatória embute —")
            print("  e é uma vantagem que não existe na vida real, porque em")
            print("  2026 ninguém tem os dados de 2027.")
            print()
            print("  Não é vazamento entre municípios (isso já foi descartado:")
            print("  bloquear por município não muda o resultado). É a própria")
            print("  base mudando de comportamento ao longo dos anos.")
        else:
            print("  Ver o futuro quase não ajuda quando o tamanho do treino é")
            print("  igual. Então a diferença observada antes vinha sobretudo da")
            print("  quantidade de dados, e não da ordem do tempo — nesse caso a")
            print("  validação aleatória é menos enganosa do que parecia.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
