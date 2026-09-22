"""
Quanto, em porcentagem, cada mudança pesquisada realmente rende?

Os experimentos anteriores compararam ESTIMATIVAS (validação aleatória contra
temporal) e variantes de modelo. Ficaram duas perguntas sem número, e são as
que decidem se vale mudar alguma coisa:

  1. Usar a validação aleatória para ESCOLHER os hiperparâmetros produz um
     modelo melhor no teste temporal?

     A ideia vem do que medimos: a validação aleatória tem desvio de ±0,4%
     contra ±4,9% da temporal. Com ruído dez vezes menor, ela deveria
     distinguir configurações que a temporal confunde — e assim escolher
     melhor. Aqui isso é testado, não suposto.

  2. Quanto a calibração melhora as porcentagens que a interface mostra?

     O modelo hoje é otimista: diz 60–80% e acontece 59%. A calibração não
     promete mexer na acurácia; promete fazer o número exibido significar o
     que diz. O ganho é medido pelo erro de Brier e pelo desvio médio entre
     o previsto e o observado.

REGRA QUE VALE PARA TUDO AQUI
-----------------------------
As duas estratégias de escolha só enxergam dados até 2021. O teste
(2022–2025) é usado uma vez, no fim, para comparar as duas escolhas. É a
única forma de a comparação ser justa — Cawley & Talbot (2010).

Não altera nada do projeto.

    python experimentos/quantificar_ganhos.py
    python experimentos/quantificar_ganhos.py --rapido
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import caracteristicas, esquema, validacao_temporal  # noqa: E402
from treinamento.treinar_modelo import construir_modelo  # noqa: E402

PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"
SEMENTE = 42
ANO_VALIDACAO = 2020
ANO_TESTE = 2022

# Espaço de busca. Pequeno de propósito: cada configuração custa um treino
# completo, e o objetivo é comparar dois CRITÉRIOS de escolha, não varrer o
# espaço todo.
CANDIDATOS = [
    {"profundidade": 10, "folha": 20},
    {"profundidade": 14, "folha": 10},
    {"profundidade": 16, "folha": 5},
    {"profundidade": 20, "folha": 5},
    {"profundidade": 26, "folha": 3},
    {"profundidade": None, "folha": 2},
]


def titulo(texto):
    print(f"\n{'=' * 74}\n{texto}\n{'=' * 74}")


def medir(y_real, y_prev):
    return {
        "balanceada": float(balanced_accuracy_score(y_real, y_prev)),
        "f1_macro": float(f1_score(y_real, y_prev, average="macro")),
        "recall_alto": float(recall_score(y_real, y_prev, labels=["alto"],
                                          average="macro", zero_division=0)),
    }


# ==========================================================================
# Pergunta 1 — qual critério escolhe melhor?
# ==========================================================================

def escolher_por_cv_aleatoria(X, y, arvores, particoes=3):
    """
    Escolhe a configuração pela validação cruzada aleatória, usando apenas os
    dados até 2021. É a proposta em discussão, aplicada ao que ela faz de
    melhor: comparar alternativas com pouco ruído.
    """
    divisor = StratifiedKFold(n_splits=particoes, shuffle=True,
                              random_state=SEMENTE)
    historico = []

    for parametros in CANDIDATOS:
        notas = []
        for treino, teste in divisor.split(X, y):
            m = construir_modelo(arvores, parametros["profundidade"], SEMENTE,
                                 parametros["folha"])
            m.fit(X.iloc[treino], y.iloc[treino])
            notas.append(f1_score(y.iloc[teste], m.predict(X.iloc[teste]),
                                  average="macro"))
        media, desvio = float(np.mean(notas)), float(np.std(notas))
        historico.append({"parametros": parametros, "f1": media, "desvio": desvio})
        print(f"    prof={str(parametros['profundidade'] or 'livre'):>5} "
              f"folha={parametros['folha']:>2}  F1={media:.4f} ±{desvio:.4f}",
              flush=True)

    melhor = max(historico, key=lambda h: h["f1"])
    return melhor["parametros"], historico


def escolher_por_validacao_temporal(X, y, treino, validacao, arvores):
    """
    Escolhe pela validação temporal — o critério usado hoje no projeto.
    Treina até 2019 e compara as configurações em 2020–2021.
    """
    historico = []

    for parametros in CANDIDATOS:
        m = construir_modelo(arvores, parametros["profundidade"], SEMENTE,
                             parametros["folha"])
        m.fit(X[treino], y[treino])
        nota = f1_score(y[validacao], m.predict(X[validacao]), average="macro")
        historico.append({"parametros": parametros, "f1": float(nota),
                          "desvio": None})
        print(f"    prof={str(parametros['profundidade'] or 'livre'):>5} "
              f"folha={parametros['folha']:>2}  F1={nota:.4f}", flush=True)

    melhor = max(historico, key=lambda h: h["f1"])
    return melhor["parametros"], historico


# ==========================================================================
# Pergunta 2 — quanto a calibração melhora as porcentagens?
# ==========================================================================

def erro_de_calibracao(p_previsto, aconteceu, faixas=10):
    """
    Erro de calibração esperado (ECE): desvio médio entre o que o modelo
    promete e o que acontece, ponderado pelo número de casos em cada faixa.

    Zero significa que, entre os casos a que o modelo dá 70%, exatamente 70%
    acontecem.
    """
    limites = np.linspace(0, 1, faixas + 1)
    erro, total = 0.0, len(p_previsto)

    for inicio, fim in zip(limites[:-1], limites[1:]):
        dentro = (p_previsto >= inicio) & (p_previsto < fim)
        if dentro.sum() == 0:
            continue
        erro += dentro.sum() * abs(
            aconteceu[dentro].mean() - p_previsto[dentro].mean()
        )
    return float(erro / total)


def avaliar_probabilidades(modelo, X, y):
    probabilidades = modelo.predict_proba(X)
    classes = list(modelo.classes_)
    p_alto = probabilidades[:, classes.index("alto")]
    aconteceu = (np.asarray(y) == "alto").astype(int)

    return {
        "brier": float(brier_score_loss(aconteceu, p_alto)),
        "erro_calibracao": erro_de_calibracao(p_alto, aconteceu),
        "media_prevista": float(p_alto.mean()),
        "media_observada": float(aconteceu.mean()),
    }


# ==========================================================================
# Execução
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mede em porcentagem o ganho de cada mudança pesquisada."
    )
    parser.add_argument("--rapido", action="store_true")
    argumentos = parser.parse_args()
    arvores = 30 if argumentos.rapido else 80

    dados = pd.read_csv(RAIZ / "dados" / "dados.csv")
    X, y = caracteristicas.separar_x_y(dados)
    treino, validacao, teste = validacao_temporal.dividir_em_tres(
        dados, ANO_VALIDACAO, ANO_TESTE
    )
    # Tudo até 2021 — é o que qualquer um dos dois critérios pode enxergar.
    ate_2021 = (treino | validacao).to_numpy()

    titulo("PERGUNTA 1 — QUAL CRITÉRIO ESCOLHE O MELHOR MODELO?")
    print("Seis configurações, dois critérios de escolha, um mesmo teste final.\n")
    inicio = time.time()

    print("  a) escolhendo pela VALIDAÇÃO CRUZADA ALEATÓRIA (até 2021):")
    escolha_cv, hist_cv = escolher_por_cv_aleatoria(
        X[ate_2021].reset_index(drop=True),
        y[ate_2021].reset_index(drop=True), arvores
    )
    print(f"    -> escolheu profundidade={escolha_cv['profundidade'] or 'livre'}, "
          f"folha={escolha_cv['folha']}")

    print("\n  b) escolhendo pela VALIDAÇÃO TEMPORAL (treina ≤2019, valida 2020–21):")
    escolha_temporal, hist_temporal = escolher_por_validacao_temporal(
        X, y, treino, validacao, arvores
    )
    print(f"    -> escolheu profundidade="
          f"{escolha_temporal['profundidade'] or 'livre'}, "
          f"folha={escolha_temporal['folha']}")

    # --- Teste final, uma vez só ------------------------------------------
    titulo("RESULTADO NO TESTE (2022–2025) — a régua comum")
    print("Cada escolha é retreinada com tudo até 2021 e medida no mesmo teste.\n")

    resultados = {}
    modelos = {}
    for rotulo, parametros in (("escolha da CV aleatória", escolha_cv),
                               ("escolha da val. temporal", escolha_temporal)):
        m = construir_modelo(arvores, parametros["profundidade"], SEMENTE,
                             parametros["folha"])
        m.fit(X[ate_2021], y[ate_2021])
        modelos[rotulo] = m
        resultados[rotulo] = medir(y[teste], m.predict(X[teste]))

    print(f"  {'critério de escolha':<28}{'balanceada':>13}{'F1 macro':>12}"
          f"{'risco alto':>13}")
    print("  " + "-" * 66)
    for rotulo, m in resultados.items():
        print(f"  {rotulo:<28}{m['balanceada']:>12.1%}{m['f1_macro']:>12.3f}"
              f"{m['recall_alto']:>13.1%}")

    a = resultados["escolha da CV aleatória"]
    t = resultados["escolha da val. temporal"]
    ganho_selecao = a["balanceada"] - t["balanceada"]

    print(f"\n  GANHO de escolher pela CV aleatória: "
          f"{ganho_selecao:+.1%} de acurácia balanceada, "
          f"{a['f1_macro'] - t['f1_macro']:+.3f} de F1")

    if escolha_cv == escolha_temporal:
        print("  (os dois critérios escolheram a MESMA configuração, então o")
        print("   ganho é zero por construção — a diferença de ruído não mudou")
        print("   a decisão neste espaço de busca)")

    # --- Pergunta 2 --------------------------------------------------------
    titulo("PERGUNTA 2 — QUANTO A CALIBRAÇÃO MELHORA AS PORCENTAGENS?")
    print("A interface mostra 'chance de ser grave'. Aqui se mede o quanto\n"
          "esse número corresponde à realidade.\n")

    base = modelos["escolha da val. temporal"]
    antes = avaliar_probabilidades(base, X[teste], y[teste])

    # A calibração é ajustada na VALIDAÇÃO, nunca no teste. O modelo entra
    # congelado: `FrozenEstimator` diz ao scikit-learn para não retreiná-lo,
    # apenas aprender a correção sobre as probabilidades que ele já produz.
    # (Nas versões antigas isso era `cv="prefit"`, removido depois da 1.6.)
    from sklearn.frozen import FrozenEstimator

    calibrados = {}
    for metodo in ("isotonic", "sigmoid"):
        c = CalibratedClassifierCV(FrozenEstimator(base), method=metodo)
        c.fit(X[validacao], y[validacao])
        calibrados[metodo] = c

    print(f"  {'versão':<26}{'Brier':>10}{'erro calib.':>14}"
          f"{'balanceada':>13}{'risco alto':>13}")
    print("  " + "-" * 76)

    m_antes = medir(y[teste], base.predict(X[teste]))
    print(f"  {'sem calibração':<26}{antes['brier']:>10.4f}"
          f"{antes['erro_calibracao']:>13.1%}{m_antes['balanceada']:>13.1%}"
          f"{m_antes['recall_alto']:>13.1%}")

    depois = {}
    for metodo, modelo in calibrados.items():
        p = avaliar_probabilidades(modelo, X[teste], y[teste])
        mm = medir(y[teste], modelo.predict(X[teste]))
        depois[metodo] = {**p, **mm}
        nome = "isotônica" if metodo == "isotonic" else "sigmoide (Platt)"
        print(f"  {nome:<26}{p['brier']:>10.4f}{p['erro_calibracao']:>13.1%}"
              f"{mm['balanceada']:>13.1%}{mm['recall_alto']:>13.1%}")

    melhor_metodo = min(depois, key=lambda k: depois[k]["erro_calibracao"])
    reducao_ece = (antes["erro_calibracao"] - depois[melhor_metodo]["erro_calibracao"])
    reducao_relativa = reducao_ece / antes["erro_calibracao"] if antes["erro_calibracao"] else 0

    titulo("RESUMO EM PORCENTAGEM")
    print(f"  1. Escolher hiperparâmetros pela CV aleatória:")
    print(f"       {ganho_selecao:+.1%} de acurácia balanceada")
    print()
    print(f"  2. Calibrar as probabilidades ({melhor_metodo}):")
    print(f"       erro de calibração: {antes['erro_calibracao']:.1%} -> "
          f"{depois[melhor_metodo]['erro_calibracao']:.1%} "
          f"({reducao_relativa:+.0%} de redução)")
    print(f"       Brier: {antes['brier']:.4f} -> {depois[melhor_metodo]['brier']:.4f}")
    print(f"       acurácia balanceada: "
          f"{depois[melhor_metodo]['balanceada'] - m_antes['balanceada']:+.1%}")
    print()
    print("  O modelo prometia em média "
          f"{antes['media_prevista']:.1%} de risco alto; aconteceu "
          f"{antes['media_observada']:.1%}.")
    print(f"  Depois de calibrar, promete "
          f"{depois[melhor_metodo]['media_prevista']:.1%}.")

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "ganhos_quantificados.json"
    saida.write_text(json.dumps({
        "arvores": arvores,
        "escolha_cv_aleatoria": escolha_cv,
        "escolha_val_temporal": escolha_temporal,
        "historico_cv": hist_cv,
        "historico_temporal": hist_temporal,
        "teste": resultados,
        "ganho_selecao_balanceada": ganho_selecao,
        "calibracao": {"antes": {**antes, **m_antes}, "depois": depois},
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSalvo em {saida.relative_to(RAIZ)}")
    print(f"Tempo: {(time.time() - inicio) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
