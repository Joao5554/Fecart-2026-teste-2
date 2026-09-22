"""
Tentativas de melhorar a acurácia — experimento isolado.

Este script **não altera o projeto**: não escreve em modelo/, não mexe no
esquema, não toca no pipeline de produção. Ele treina variantes, mede todas
com a mesma régua e grava um relatório. Se alguma ideia se mostrar melhor,
aí sim vale discutir levá-la para o modelo oficial.

    python experimentos/melhorar_modelo.py
    python experimentos/melhorar_modelo.py --rapido

AS QUATRO IDEIAS TESTADAS
-------------------------
1. **Gradient boosting em vez de floresta.** Em dados tabulares, árvores
   impulsionadas costumam superar Random Forest, porque cada árvore corrige
   o erro da anterior em vez de votar em paralelo.

2. **Decomposição hierárquica.** O rótulo não é uma categoria solta: ele foi
   construído em duas etapas — primeiro "houve ocorrência?", depois "foi
   grave?". Um modelo multiclasse comum ignora essa ordem. Aqui o problema é
   quebrado em dois classificadores binários que espelham a construção real:

       P(alto)  = P(houve) × P(grave | houve)
       P(medio) = P(houve) × (1 − P(grave | houve))
       P(baixo) = 1 − P(houve)

   É a estrutura conhecida como *nested dichotomies* / modelo de razões
   contínuas, apropriada quando as classes têm ordem natural.

3. **Limiar de decisão ajustado.** Todo classificador escolhe a classe de
   maior probabilidade, o que equivale a assumir que todo erro custa igual.
   Num sistema de alerta não custa: deixar de avisar é pior que alarme falso.
   O limiar é escolhido na VALIDAÇÃO — nunca no teste.

4. **Calibração das probabilidades.** A interface mostra "72% de chance de
   ser grave". Isso só é honesto se, entre os casos com 72%, cerca de 72%
   forem mesmo graves. O erro de Brier e a calibração medem isso, e é
   possível ter acurácia boa com probabilidade mal calibrada.

CUIDADO METODOLÓGICO
--------------------
Todas as escolhas (modelo, limiar, calibração) são feitas no conjunto de
VALIDAÇÃO (2020–2021). O teste (2022–2025) é usado uma única vez, no fim.
Escolher olhando o teste produziria um número otimista que não se repete —
Cawley & Talbot (2010), JMLR 11:2079-2107.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    recall_score,
)

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import caracteristicas, esquema, validacao_temporal  # noqa: E402
from treinamento.treinar_modelo import PESOS_CLASSE, construir_modelo  # noqa: E402

ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

SEMENTE = 42
ANO_VALIDACAO = 2020
ANO_TESTE = 2022


def titulo(texto: str) -> None:
    print(f"\n{'=' * 74}\n{texto}\n{'=' * 74}")


def medir(y_real, y_previsto) -> dict:
    return {
        "balanceada": float(balanced_accuracy_score(y_real, y_previsto)),
        "f1_macro": float(f1_score(y_real, y_previsto, average="macro")),
        "recall_alto": float(recall_score(y_real, y_previsto, labels=["alto"],
                                          average="macro", zero_division=0)),
    }


def linha(nome, m, extra=""):
    print(f"  {nome:<38}{m['balanceada']:>11.1%}{m['f1_macro']:>11.3f}"
          f"{m['recall_alto']:>12.1%}  {extra}")


# ==========================================================================
# 1. Gradient boosting
# ==========================================================================

class Boosting:
    """
    Árvores impulsionadas com suporte nativo a valor faltante.

    O HistGradientBoosting trata NaN sozinho, aprendendo para que lado mandar
    o valor ausente — útil aqui, onde ~23% das linhas não têm dados de chuva.

    Os pesos das classes entram por LINHA, e não pelo parâmetro `class_weight`:
    esse estimador recodifica o alvo como 0/1/2 antes de aplicar os pesos, e
    um dicionário com os nomes das classes não é encontrado. Passar
    `sample_weight` dá o mesmo efeito e não depende dessa recodificação.
    """

    def __init__(self, semente=SEMENTE):
        from sklearn.pipeline import Pipeline

        self.pipeline = Pipeline([
            ("preparacao", caracteristicas.construir_preprocessador()),
            ("boosting", HistGradientBoostingClassifier(
                max_iter=300,
                learning_rate=0.08,
                max_leaf_nodes=31,
                min_samples_leaf=40,
                l2_regularization=1.0,
                early_stopping=True,
                validation_fraction=0.12,
                random_state=semente,
            )),
        ])

    def fit(self, X, y):
        pesos = np.array([PESOS_CLASSE[classe] for classe in y])
        self.pipeline.fit(X, y, boosting__sample_weight=pesos)
        self.classes_ = self.pipeline.named_steps["boosting"].classes_
        return self

    def predict(self, X):
        return self.pipeline.predict(X)

    def predict_proba(self, X):
        return self.pipeline.predict_proba(X)


def construir_boosting(semente=SEMENTE):
    return Boosting(semente)


# ==========================================================================
# 2. Decomposição hierárquica
# ==========================================================================

class ModeloHierarquico:
    """
    Dois classificadores binários que espelham como o rótulo foi construído.

    O primeiro responde "houve ocorrência neste mês?". O segundo, treinado
    apenas nas linhas em que houve, responde "foi grave?". As probabilidades
    das três classes saem da regra da cadeia.

    A vantagem esperada é usar melhor os dados: o segundo modelo não precisa
    gastar capacidade separando "nada aconteceu", e pode se concentrar no que
    distingue um evento grave de um evento comum.
    """

    def __init__(self, criar_modelo):
        self.criar_modelo = criar_modelo
        self.classes_ = np.array(esquema.CLASSES_RISCO)

    def fit(self, X, y):
        houve = (y != "baixo").astype(int)
        self.modelo_ocorrencia = self.criar_modelo()
        self.modelo_ocorrencia.fit(X, houve)

        com_evento = y != "baixo"
        grave = (y[com_evento] == "alto").astype(int)
        self.modelo_gravidade = self.criar_modelo()
        self.modelo_gravidade.fit(X[com_evento], grave)
        return self

    def predict_proba(self, X):
        p_houve = self.modelo_ocorrencia.predict_proba(X)[:, 1]
        p_grave = self.modelo_gravidade.predict_proba(X)[:, 1]

        return np.column_stack([
            1.0 - p_houve,               # baixo
            p_houve * (1.0 - p_grave),   # medio
            p_houve * p_grave,           # alto
        ])

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]


def binario_com_pesos(peso_positivo: float):
    """Fábrica de classificadores binários para o modelo hierárquico."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline

    def criar():
        return Pipeline([
            ("preparacao", caracteristicas.construir_preprocessador()),
            ("floresta", RandomForestClassifier(
                n_estimators=100, max_depth=16, min_samples_leaf=5,
                class_weight={0: 1.0, 1: peso_positivo},
                n_jobs=-1, random_state=SEMENTE,
            )),
        ])

    return criar


# ==========================================================================
# 3. Limiar de decisão
# ==========================================================================

def escolher_limiar(modelo, X_val, y_val) -> tuple[float, dict]:
    """
    Procura o limiar de "alto" que maximiza o F1 macro na VALIDAÇÃO.

    Em vez de escolher sempre a classe de maior probabilidade, marca como
    "alto" tudo que passa de um limiar. Limiar baixo pega mais casos graves e
    gera mais alarme falso; a busca encontra o ponto de melhor equilíbrio.
    """
    probabilidades = modelo.predict_proba(X_val)
    classes = list(getattr(modelo, "classes_", esquema.CLASSES_RISCO))
    i_alto = classes.index("alto")

    melhor, melhor_nota = 0.5, -1.0
    for limiar in np.arange(0.10, 0.75, 0.025):
        previsto = _aplicar_limiar(probabilidades, classes, i_alto, limiar)
        nota = f1_score(y_val, previsto, average="macro")
        if nota > melhor_nota:
            melhor, melhor_nota = float(limiar), float(nota)

    return melhor, {"f1_macro_validacao": melhor_nota}


def _aplicar_limiar(probabilidades, classes, i_alto, limiar):
    """Marca 'alto' acima do limiar; abaixo, decide entre as demais classes."""
    outras = [i for i in range(len(classes)) if i != i_alto]
    escolha_restante = np.array(classes)[
        [outras[i] for i in probabilidades[:, outras].argmax(axis=1)]
    ]
    return np.where(probabilidades[:, i_alto] >= limiar, "alto", escolha_restante)


# ==========================================================================
# 4. Calibração
# ==========================================================================

def avaliar_calibracao(modelo, X, y) -> dict:
    """
    Erro de Brier e confronto entre probabilidade prevista e frequência real.

    Um modelo bem calibrado acerta a frequência: entre os casos a que ele dá
    70%, cerca de 70% devem ser mesmo graves. Isso é independente de acurácia
    — dá para acertar muito e mesmo assim comunicar probabilidade errada.
    """
    probabilidades = modelo.predict_proba(X)
    classes = list(getattr(modelo, "classes_", esquema.CLASSES_RISCO))
    p_alto = probabilidades[:, classes.index("alto")]
    real = (np.asarray(y) == "alto").astype(int)

    faixas = []
    for inicio in np.arange(0, 1.0, 0.2):
        dentro = (p_alto >= inicio) & (p_alto < inicio + 0.2)
        if dentro.sum() >= 50:
            faixas.append({
                "faixa": f"{inicio:.0%}–{inicio + 0.2:.0%}",
                "previsto_medio": float(p_alto[dentro].mean()),
                "observado": float(real[dentro].mean()),
                "n": int(dentro.sum()),
            })

    return {
        "brier": float(brier_score_loss(real, p_alto)),
        "faixas": faixas,
    }


# ==========================================================================
# Execução
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Testa melhorias de acurácia. Não altera o projeto."
    )
    parser.add_argument("--dados", type=Path, default=ARQUIVO_DADOS)
    parser.add_argument("--rapido", action="store_true")
    argumentos = parser.parse_args()

    arvores = 30 if argumentos.rapido else 100

    if not argumentos.dados.exists():
        print(f"Dataset não encontrado: {argumentos.dados}", file=sys.stderr)
        return 1

    titulo("TENTATIVAS DE MELHORAR A ACURÁCIA")
    dados = pd.read_csv(argumentos.dados)
    X, y = caracteristicas.separar_x_y(dados)

    treino, validacao, teste = validacao_temporal.dividir_em_tres(
        dados, ANO_VALIDACAO, ANO_TESTE
    )
    X_tr, y_tr = X[treino], y[treino]
    X_val, y_val = X[validacao], y[validacao]
    X_te, y_te = X[teste], y[teste]

    print(f"treino {int(treino.sum()):,} · validação {int(validacao.sum()):,} "
          f"· teste {int(teste.sum()):,}")
    print("Escolhas feitas na validação; o teste é usado uma vez só, no fim.")

    inicio = time.time()
    variantes = {}

    # --- Referência --------------------------------------------------------
    titulo("TREINANDO AS VARIANTES")
    print("  referência: Random Forest multiclasse (o do projeto)...", flush=True)
    referencia = construir_modelo(arvores, 16, SEMENTE, 5).fit(X_tr, y_tr)
    variantes["floresta_multiclasse"] = referencia

    print("  gradient boosting...", flush=True)
    variantes["gradient_boosting"] = construir_boosting().fit(X_tr, y_tr)

    print("  hierárquico (ocorrência × gravidade)...", flush=True)
    variantes["hierarquico"] = ModeloHierarquico(
        binario_com_pesos(3.0)
    ).fit(X_tr, y_tr)

    print("  hierárquico com peso maior no evento grave...", flush=True)
    variantes["hierarquico_peso_alto"] = ModeloHierarquico(
        binario_com_pesos(6.0)
    ).fit(X_tr, y_tr)

    # --- Escolha na validação ---------------------------------------------
    titulo("DESEMPENHO NA VALIDAÇÃO (2020–2021) — é aqui que se escolhe")
    print(f"  {'variante':<38}{'balanceada':>11}{'F1 macro':>11}{'risco alto':>12}")
    print("  " + "-" * 72)

    notas_validacao = {}
    for nome, modelo in variantes.items():
        m = medir(y_val, modelo.predict(X_val))
        notas_validacao[nome] = m
        linha(nome, m)

    melhor_nome = max(notas_validacao, key=lambda k: notas_validacao[k]["f1_macro"])
    print(f"\n  Melhor na validação: {melhor_nome}")

    # --- Limiar ------------------------------------------------------------
    titulo("AJUSTE DO LIMIAR DE DECISÃO (também na validação)")
    limiar, info_limiar = escolher_limiar(variantes[melhor_nome], X_val, y_val)
    print(f"  Limiar escolhido para 'alto': {limiar:.3f}")
    print(f"  F1 macro na validação com esse limiar: "
          f"{info_limiar['f1_macro_validacao']:.3f}")

    # --- Teste, uma vez só -------------------------------------------------
    titulo("TESTE (2022–2025) — usado uma única vez")
    print(f"  {'variante':<38}{'balanceada':>11}{'F1 macro':>11}{'risco alto':>12}")
    print("  " + "-" * 72)

    notas_teste = {}
    for nome, modelo in variantes.items():
        m = medir(y_te, modelo.predict(X_te))
        notas_teste[nome] = m
        linha(nome, m, "<- referência" if nome == "floresta_multiclasse" else "")

    modelo_escolhido = variantes[melhor_nome]
    probabilidades = modelo_escolhido.predict_proba(X_te)
    classes = list(getattr(modelo_escolhido, "classes_", esquema.CLASSES_RISCO))
    com_limiar = _aplicar_limiar(probabilidades, classes,
                                 classes.index("alto"), limiar)
    m_limiar = medir(y_te, com_limiar)
    notas_teste[f"{melhor_nome} + limiar {limiar:.2f}"] = m_limiar
    linha(f"{melhor_nome} + limiar", m_limiar, "<- com ajuste")

    # --- Comparação com a referência ---------------------------------------
    base = notas_teste["floresta_multiclasse"]
    titulo("GANHO SOBRE O MODELO ATUAL")
    print(f"  {'variante':<44}{'balanceada':>13}{'F1 macro':>12}{'risco alto':>13}")
    print("  " + "-" * 80)
    for nome, m in notas_teste.items():
        if nome == "floresta_multiclasse":
            continue
        print(f"  {nome:<44}"
              f"{m['balanceada'] - base['balanceada']:>+12.1%}"
              f"{m['f1_macro'] - base['f1_macro']:>+12.3f}"
              f"{m['recall_alto'] - base['recall_alto']:>+12.1%}")

    # --- Calibração --------------------------------------------------------
    titulo("QUALIDADE DAS PROBABILIDADES (calibração)")
    print("  A interface mostra porcentagens; elas precisam significar algo.\n")
    for nome in ("floresta_multiclasse", melhor_nome):
        cal = avaliar_calibracao(variantes[nome], X_te, y_te)
        print(f"  {nome} — erro de Brier: {cal['brier']:.4f} "
              f"(quanto menor, melhor)")
        for f in cal["faixas"]:
            desvio = f["observado"] - f["previsto_medio"]
            print(f"     dizia {f['faixa']:<9} aconteceu {f['observado']:>6.1%}"
                  f"   desvio {desvio:>+6.1%}   ({f['n']:,} casos)")
        print()

    # --- Gravação ----------------------------------------------------------
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "melhorias.json"
    saida.write_text(json.dumps({
        "divisao": {"validacao": ANO_VALIDACAO, "teste": ANO_TESTE},
        "arvores": arvores,
        "validacao": notas_validacao,
        "melhor_na_validacao": melhor_nome,
        "limiar_escolhido": limiar,
        "teste": notas_teste,
        "calibracao": {
            nome: avaliar_calibracao(variantes[nome], X_te, y_te)
            for nome in ("floresta_multiclasse", melhor_nome)
        },
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Resultado salvo em {saida.relative_to(RAIZ)}")
    print(f"Tempo total: {(time.time() - inicio) / 60:.1f} min")
    print("\nNada do projeto foi alterado: este script só lê dados e grava")
    print("o relatório em experimentos/resultados/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
