"""
Quando o modelo diz 60%, acontece 60% das vezes?

Acurácia e confiabilidade são perguntas diferentes, e a interface mostra as
duas: o SELO ("risco alto") é acurácia, a PORCENTAGEM ao lado é confiabilidade.
Um modelo pode acertar muito o selo e mentir na porcentagem — basta prever
sempre 90% para os casos que acerta.

A medida certa aqui chama-se calibração, e este script produz as três formas
de olhar para ela:

  1. a tabela de confiabilidade — o que foi prometido contra o que aconteceu,
     faixa por faixa;
  2. o erro de calibração esperado (ECE), que resume a tabela num número,
     pesando cada faixa pelo número de casos;
  3. o escore de Brier, que mistura calibração e capacidade de separar — é o
     erro quadrático médio da probabilidade.

Protocolo idêntico ao do treino de produção: treina com tudo até 2021, mede
em 2022–2025, sem tocar no teste para escolher coisa nenhuma.

Como rodar (a partir da raiz do projeto):
    python experimentos/confiabilidade.py

Nada aqui altera o modelo em produção.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import caracteristicas, esquema  # noqa: E402
from src.carregar import carregar_dados  # noqa: E402
from treinamento.treinar_modelo import (  # noqa: E402
    ajustar, construir_boosting,
)
from quantificar_ganhos import erro_de_calibracao  # noqa: E402

ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

SEMENTE = 42
ANO_CORTE = 2022

# Faixas de 10 em 10 pontos. Mais estreitas dariam faixas com poucos casos, e
# a frequência observada viraria ruído.
FAIXAS = np.linspace(0.0, 1.0, 11)


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def tabela_de_confiabilidade(p_previsto, aconteceu) -> list[dict]:
    """O que o modelo prometeu contra o que de fato aconteceu, faixa a faixa."""
    linhas = []
    for inicio, fim in zip(FAIXAS[:-1], FAIXAS[1:]):
        # A última faixa inclui o 1,0; as outras, não — senão um caso com
        # probabilidade exatamente 1,0 ficaria de fora de todas.
        dentro = ((p_previsto >= inicio) & (p_previsto < fim)) if fim < 1.0 \
            else ((p_previsto >= inicio) & (p_previsto <= fim))
        if dentro.sum() == 0:
            continue
        linhas.append({
            "faixa": f"{inicio:.0%}–{fim:.0%}",
            "casos": int(dentro.sum()),
            "prometido": float(p_previsto[dentro].mean()),
            "aconteceu": float(aconteceu[dentro].mean()),
        })
    return linhas


def main() -> int:
    titulo("CONFIABILIDADE: O QUE O MODELO PROMETE CONTRA O QUE ACONTECE")

    dados = carregar_dados(ARQUIVO_DADOS)
    X, y = caracteristicas.separar_x_y(dados)
    anos = dados["ano"]

    treino = anos < ANO_CORTE
    teste = anos >= ANO_CORTE
    print(f"Treino: {int(anos[treino].min())}–{ANO_CORTE - 1} "
          f"({int(treino.sum()):,} linhas)")
    print(f"Teste:  {ANO_CORTE}–{int(anos[teste].max())} "
          f"({int(teste.sum()):,} linhas)")

    print("\nTreinando com a mesma configuração da produção...", flush=True)
    modelo = ajustar(construir_boosting(SEMENTE), X[treino], y[treino])

    classes = list(modelo.classes_)
    probabilidades = modelo.predict_proba(X[teste])
    p_alto = probabilidades[:, classes.index("alto")]
    aconteceu = (y[teste].to_numpy() == "alto").astype(int)

    # ------------------------------------------------------------------ 1
    titulo("A TABELA DE CONFIABILIDADE")
    print("Entre os casos a que o modelo deu X% de chance de risco alto,")
    print("quantos foram de fato risco alto?\n")
    print(f"{'faixa':>10}{'casos':>10}{'prometido':>12}{'aconteceu':>12}"
          f"{'diferença':>12}   ")
    print("-" * 70)

    linhas = tabela_de_confiabilidade(p_alto, aconteceu)
    for l in linhas:
        desvio = l["aconteceu"] - l["prometido"]
        # Barra simples: para que lado erra, e quanto.
        marca = ("otimista" if desvio < -0.03
                 else "pessimista" if desvio > 0.03 else "no ponto")
        print(f"{l['faixa']:>10}{l['casos']:>10,}{l['prometido']:>12.1%}"
              f"{l['aconteceu']:>12.1%}{desvio:>+12.1%}   {marca}")

    # ------------------------------------------------------------------ 2
    titulo("OS NÚMEROS QUE RESUMEM")
    ece = erro_de_calibracao(p_alto, aconteceu)
    brier = float(brier_score_loss(aconteceu, p_alto))

    print(f"  Erro de calibração esperado (ECE):  {ece:.1%}")
    print("     Desvio médio entre prometido e acontecido, pesando cada faixa")
    print("     pelo número de casos. Abaixo de 5% costuma ser considerado")
    print("     bem calibrado; 0% seria promessa perfeita.\n")

    print(f"  Escore de Brier:                    {brier:.4f}")
    print(f"  Brier de quem chuta a média sempre: "
          f"{aconteceu.mean() * (1 - aconteceu.mean()):.4f}")
    print("     Menor é melhor. O segundo é a baliza: um 'modelo' que ignora")
    print("     tudo e responde sempre a taxa média de risco alto.\n")

    print(f"  Taxa real de risco alto no teste:   {aconteceu.mean():.1%}")
    print(f"  Média prometida pelo modelo:        {p_alto.mean():.1%}")

    # ------------------------------------------------------------------ 3
    titulo("A LEITURA PRÁTICA: QUANDO ELE CRAVA 'ALTO', ACERTA QUANTO?")
    previsto = np.array(classes)[probabilidades.argmax(axis=1)]
    y_teste = y[teste].to_numpy()

    print(f"{'quando o modelo diz':>22}{'casos':>10}{'era de fato':>14}"
          f"{'acerto':>10}")
    print("-" * 58)
    for classe in esquema.CLASSES_RISCO:
        disse = previsto == classe
        if disse.sum() == 0:
            continue
        acerto = (y_teste[disse] == classe).mean()
        print(f"{classe:>22}{int(disse.sum()):>10,}"
              f"{classe:>14}{acerto:>10.1%}")

    # O erro que mais importa num sistema de alerta.
    era_alto = y_teste == "alto"
    perdidos = ((previsto == "baixo") & era_alto).sum()
    print(f"\n  De {int(era_alto.sum()):,} casos que eram risco ALTO:")
    print(f"    {int(((previsto == 'alto') & era_alto).sum()):,} foram "
          f"avisados como alto  ({(previsto[era_alto] == 'alto').mean():.1%})")
    print(f"    {int(perdidos):,} passaram como BAIXO  "
          f"({perdidos / era_alto.sum():.1%}) — o erro mais grave possível")

    # ------------------------------------------------------------------ 4
    titulo("A CONFIABILIDADE VARIA COM O ANO?")
    print(f"{'ano':>6}{'casos':>10}{'taxa real':>12}{'prometido':>12}"
          f"{'ECE':>10}")
    print("-" * 50)
    por_ano = []
    anos_teste = anos[teste].to_numpy()
    for ano in sorted(set(anos_teste)):
        dentro = anos_teste == ano
        registro = {
            "ano": int(ano),
            "casos": int(dentro.sum()),
            "taxa_real": float(aconteceu[dentro].mean()),
            "prometido": float(p_alto[dentro].mean()),
            "ece": erro_de_calibracao(p_alto[dentro], aconteceu[dentro]),
        }
        por_ano.append(registro)
        print(f"{registro['ano']:>6}{registro['casos']:>10,}"
              f"{registro['taxa_real']:>12.1%}{registro['prometido']:>12.1%}"
              f"{registro['ece']:>10.1%}")

    # ------------------------------------------------------------------ 5
    titulo("DE ONDE VEM O OTIMISMO: OS PESOS DE CLASSE")
    print("O modelo é treinado com peso 6 para 'alto' e 1 para 'baixo' — ou")
    print("seja, mandaram nele que deixar de avisar um caso grave custa seis")
    print("vezes mais que um alarme falso. Se a hipótese estiver certa, tirar")
    print("os pesos deve calibrar a porcentagem E derrubar a detecção.\n")

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.pipeline import Pipeline
    from treinamento.treinar_modelo import CONFIG_BOOSTING

    neutro = Pipeline([
        ("preparacao", caracteristicas.construir_preprocessador()),
        ("boosting", HistGradientBoostingClassifier(
            random_state=SEMENTE, **CONFIG_BOOSTING
        )),
    ]).fit(X[treino], y[treino])   # sem sample_weight: todas as classes iguais

    p_neutro = neutro.predict_proba(X[teste])[:, list(neutro.classes_).index("alto")]
    previsto_neutro = np.array(neutro.classes_)[
        neutro.predict_proba(X[teste]).argmax(axis=1)
    ]

    comparacao = {
        "com pesos (produção)": {
            "media_prometida": float(p_alto.mean()),
            "ece": ece,
            "brier": brier,
            "recall_alto": float((previsto[era_alto] == "alto").mean()),
        },
        "sem pesos": {
            "media_prometida": float(p_neutro.mean()),
            "ece": erro_de_calibracao(p_neutro, aconteceu),
            "brier": float(brier_score_loss(aconteceu, p_neutro)),
            "recall_alto": float((previsto_neutro[era_alto] == "alto").mean()),
        },
    }

    print(f"{'':<24}{'prometido':>12}{'ECE':>9}{'Brier':>10}"
          f"{'risco alto pego':>18}")
    print("-" * 73)
    for nome, m in comparacao.items():
        print(f"  {nome:<22}{m['media_prometida']:>12.1%}{m['ece']:>9.1%}"
              f"{m['brier']:>10.4f}{m['recall_alto']:>18.1%}")
    print(f"\n  Taxa real: {aconteceu.mean():.1%}")

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "confiabilidade.json"
    saida.write_text(json.dumps({
        "periodo_teste": f"{ANO_CORTE}-{int(anos.max())}",
        "linhas_teste": int(teste.sum()),
        "ece": ece,
        "brier": brier,
        "brier_baliza": float(aconteceu.mean() * (1 - aconteceu.mean())),
        "taxa_real": float(aconteceu.mean()),
        "media_prometida": float(p_alto.mean()),
        "tabela": linhas,
        "por_ano": por_ano,
        "efeito_dos_pesos": comparacao,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
