"""
Comparação de estratégias de validação — experimento isolado.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Surgiu a sugestão de trocar a validação temporal por validação aleatória,
sob o argumento de que a divisão por período sequencial poderia enganar a
acurácia. A dúvida é legítima e merece resposta com número, não com opinião.

Este script mede QUATRO estratégias sobre exatamente o mesmo modelo e os
mesmos dados, e mostra a distância entre elas. Ele **não altera nada** do
projeto: não escreve em modelo/, não mexe em dados/, não toca no esquema.
Rodar e apagar não muda uma vírgula do sistema em produção.

    python experimentos/comparar_validacao.py
    python experimentos/comparar_validacao.py --rapido

O QUE DIZ A LITERATURA
----------------------
* **Roberts et al. (2017), Ecography 40:913-929** — "Cross-validation
  strategies for data with temporal, spatial, hierarchical, or phylogenetic
  structure". Quando existe estrutura de dependência nos dados, a validação
  aleatória subestima seriamente o erro de previsão. Recomendam validação
  em blocos sempre que houver dependência, mesmo que os resíduos do modelo
  não mostrem correlação aparente.

* **Bergmeir, Hyndman & Koo (2018), Comput. Stat. Data Anal. 120:70-83** —
  "A note on the validity of cross-validation for evaluating autoregressive
  time series prediction". Mostram que a validação cruzada aleatória PODE
  ser válida em séries temporais, **desde que** o modelo seja puramente
  autorregressivo e os erros não sejam correlacionados. É a defesa técnica
  mais forte da validação aleatória — e vale conferir se o caso se aplica
  aqui.

* **Cawley & Talbot (2010), JMLR 11:2079-2107** — "On over-fitting in model
  selection and subsequent selection bias in performance evaluation".
  Escolher hiperparâmetros com a mesma partição usada para relatar o
  desempenho introduz viés otimista. A correção é validação aninhada.

O QUE ESTE PROJETO TEM DE ESTRUTURA
-----------------------------------
1. **Temporal** — as features de um mês vêm do passado daquele município.
2. **Agrupada** — o mesmo município aparece em dezenas de linhas. Numa
   divisão aleatória, Petrópolis cai no treino E no teste, e o modelo pode
   simplesmente decorar "Petrópolis é perigosa" em vez de aprender por quê.
3. **Deriva** — a taxa de ocorrências registradas sobe de ~19% (2010) para
   ~34% (2023), por aumento real de eventos e por melhora da notificação.

O ponto 2 é o que a condição de Bergmeir et al. não cobre: o modelo aqui
não é puramente autorregressivo, e os erros de um mesmo município são
correlacionados entre si.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, recall_score
from sklearn.model_selection import (
    GroupKFold,
    RepeatedStratifiedKFold,
    StratifiedKFold,
)

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import caracteristicas, esquema, validacao_temporal  # noqa: E402
from treinamento.treinar_modelo import construir_modelo  # noqa: E402

ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

SEMENTE = 42
ANO_CORTE = 2022


def titulo(texto: str) -> None:
    print(f"\n{'=' * 74}\n{texto}\n{'=' * 74}")


def medir(y_real, y_previsto) -> dict:
    return {
        "balanceada": float(balanced_accuracy_score(y_real, y_previsto)),
        "f1_macro": float(f1_score(y_real, y_previsto, average="macro")),
        "recall_alto": float(recall_score(y_real, y_previsto, labels=["alto"],
                                          average="macro", zero_division=0)),
    }


def resumir(notas: list[dict], nome: str, detalhe: str) -> dict:
    tabela = pd.DataFrame(notas)
    return {
        "estrategia": nome,
        "detalhe": detalhe,
        "n_particoes": len(notas),
        **{
            f"{metrica}_{estatistica}": float(getattr(tabela[metrica], estatistica)())
            for metrica in ("balanceada", "f1_macro", "recall_alto")
            for estatistica in ("mean", "std")
        },
    }


# ==========================================================================
# As quatro estratégias
# ==========================================================================

def kfold_aleatorio(X, y, arvores, repeticoes=2, particoes=5) -> dict:
    """
    Validação cruzada aleatória estratificada — a proposta em discussão.

    Sorteia as linhas sem olhar para tempo nem para município. É o padrão em
    problemas sem estrutura, e tem uma vantagem real: usa todos os dados em
    todas as posições, então a estimativa tem variância menor.
    """
    divisor = RepeatedStratifiedKFold(n_splits=particoes, n_repeats=repeticoes,
                                      random_state=SEMENTE)
    notas = []
    for treino, teste in divisor.split(X, y):
        modelo = construir_modelo(arvores, 16, SEMENTE, 5)
        modelo.fit(X.iloc[treino], y.iloc[treino])
        notas.append(medir(y.iloc[teste], modelo.predict(X.iloc[teste])))
        print(f"    partição {len(notas)}/{particoes * repeticoes}: "
              f"bal={notas[-1]['balanceada']:.3f}", flush=True)

    return resumir(notas, "aleatória (K-fold estratificado)",
                   f"{particoes} partições × {repeticoes} repetições, linhas sorteadas")


def kfold_por_municipio(X, y, grupos, arvores, particoes=5) -> dict:
    """
    Validação em blocos por município — cada cidade fica inteira de um lado.

    Responde a uma pergunta diferente e mais dura: o modelo funciona numa
    cidade que ele NUNCA viu? Se o desempenho cair muito em relação ao
    aleatório, é sinal de que boa parte do acerto vinha de decorar o nível
    de risco de cada município, não de aprender o mecanismo.

    É o esquema recomendado por Roberts et al. (2017) para dados agrupados.
    """
    divisor = GroupKFold(n_splits=particoes)
    notas = []
    for treino, teste in divisor.split(X, y, groups=grupos):
        modelo = construir_modelo(arvores, 16, SEMENTE, 5)
        modelo.fit(X.iloc[treino], y.iloc[treino])
        notas.append(medir(y.iloc[teste], modelo.predict(X.iloc[teste])))
        print(f"    partição {len(notas)}/{particoes}: "
              f"bal={notas[-1]['balanceada']:.3f}", flush=True)

    return resumir(notas, "blocos por município",
                   f"{particoes} partições, cada cidade inteira de um lado só")


def kfold_por_uf(X, y, ufs, arvores, particoes=5) -> dict:
    """
    Validação em blocos por UF — o bloco espacial mais largo possível aqui.

    Testa se o modelo generaliza para um estado inteiro que não estava no
    treino. É a versão mais severa: além do município, tira do treino toda a
    vizinhança e o contexto regional daquele lugar.
    """
    divisor = GroupKFold(n_splits=particoes)
    notas = []
    for treino, teste in divisor.split(X, y, groups=ufs):
        modelo = construir_modelo(arvores, 16, SEMENTE, 5)
        modelo.fit(X.iloc[treino], y.iloc[treino])
        notas.append(medir(y.iloc[teste], modelo.predict(X.iloc[teste])))
        print(f"    partição {len(notas)}/{particoes}: "
              f"bal={notas[-1]['balanceada']:.3f}", flush=True)

    return resumir(notas, "blocos por estado",
                   f"{particoes} partições, UFs inteiras fora do treino")


def walk_forward(X, y, anos, arvores) -> dict:
    """
    Janela expansiva — o que o projeto usa hoje.

    Treina até um ano, testa no seguinte, avança. É a única das quatro que
    respeita a ordem do tempo, e a única que reproduz a situação real de uso:
    em janeiro de 2026 só existe o que aconteceu até dezembro de 2025.
    """
    janelas = validacao_temporal.gerar_janelas(anos)
    notas = []

    for ano_treino, ano_teste in janelas:
        treino = (anos <= ano_treino).to_numpy()
        teste = (anos == ano_teste).to_numpy()
        if teste.sum() == 0:
            continue
        modelo = construir_modelo(arvores, 16, SEMENTE, 5)
        modelo.fit(X[treino], y[treino])
        notas.append(medir(y[teste], modelo.predict(X[teste])))
        print(f"    treina até {ano_treino}, testa {ano_teste}: "
              f"bal={notas[-1]['balanceada']:.3f}", flush=True)

    return resumir(notas, "temporal (janela expansiva)",
                   f"{len(notas)} janelas, treina no passado e testa no futuro")


# ==========================================================================
# Diagnóstico: quanto o modelo depende de decorar o município
# ==========================================================================

def teste_de_memorizacao(X, y, grupos, arvores) -> dict:
    """
    Mede diretamente o efeito que a validação aleatória esconde.

    Treina UMA vez e avalia em dois conjuntos de teste do mesmo tamanho:
      (a) linhas de municípios que também estão no treino;
      (b) linhas de municípios inteiramente fora do treino.

    Se (a) for muito melhor que (b), o modelo está usando a identidade do
    município — e a validação aleatória, que sempre cai no caso (a), reporta
    um número que não se sustenta em cidade nova.
    """
    rng = np.random.default_rng(SEMENTE)
    municipios = np.array(sorted(grupos.unique()))
    rng.shuffle(municipios)

    corte = int(len(municipios) * 0.8)
    conhecidos = set(municipios[:corte])

    eh_conhecido = grupos.isin(conhecidos).to_numpy()
    indices = np.arange(len(X))

    # Do conjunto de municípios conhecidos, 20% das linhas ficam fora do
    # treino para servir de teste "mesma cidade".
    linhas_conhecidas = indices[eh_conhecido]
    rng.shuffle(linhas_conhecidas)
    reservadas = set(linhas_conhecidas[: int(len(linhas_conhecidas) * 0.2)])

    treino = np.array([i for i in linhas_conhecidas if i not in reservadas])
    teste_mesma_cidade = np.array(sorted(reservadas))
    teste_cidade_nova = indices[~eh_conhecido]

    modelo = construir_modelo(arvores, 16, SEMENTE, 5)
    modelo.fit(X.iloc[treino], y.iloc[treino])

    # Mesmo tamanho nos dois testes, para a comparação ser justa.
    n = min(len(teste_mesma_cidade), len(teste_cidade_nova))
    mesma = rng.choice(teste_mesma_cidade, n, replace=False)
    nova = rng.choice(teste_cidade_nova, n, replace=False)

    resultado = {
        "n_por_grupo": int(n),
        "municipios_no_treino": len(conhecidos),
        "municipios_novos": int(len(municipios) - corte),
        "mesma_cidade": medir(y.iloc[mesma], modelo.predict(X.iloc[mesma])),
        "cidade_nova": medir(y.iloc[nova], modelo.predict(X.iloc[nova])),
    }
    resultado["queda_balanceada"] = (
        resultado["mesma_cidade"]["balanceada"]
        - resultado["cidade_nova"]["balanceada"]
    )
    return resultado


# ==========================================================================
# Execução
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara estratégias de validação. Não altera o projeto."
    )
    parser.add_argument("--dados", type=Path, default=ARQUIVO_DADOS)
    parser.add_argument("--rapido", action="store_true",
                        help="30 árvores em vez de 100; roda em poucos minutos")
    parser.add_argument("--repeticoes", type=int, default=2,
                        help="repetições do K-fold aleatório (padrão: 2)")
    argumentos = parser.parse_args()

    arvores = 30 if argumentos.rapido else 100

    if not argumentos.dados.exists():
        print(f"Dataset não encontrado: {argumentos.dados}\n"
              "Rode antes: python dados/preparar_dados.py", file=sys.stderr)
        return 1

    titulo("COMPARAÇÃO DE ESTRATÉGIAS DE VALIDAÇÃO")
    dados = pd.read_csv(argumentos.dados)
    X, y = caracteristicas.separar_x_y(dados)
    print(f"{len(dados):,} linhas · {dados['codigo_ibge'].nunique():,} municípios "
          f"· {dados['ano'].min()}–{dados['ano'].max()}")
    print(f"Modelo: Random Forest com {arvores} árvores, profundidade 16")
    print("\nEste experimento NÃO altera o modelo nem os dados do projeto.")

    inicio = time.time()
    resultados = []

    titulo("1. ALEATÓRIA — K-fold estratificado")
    print("Linhas sorteadas, sem olhar tempo nem município.\n")
    resultados.append(kfold_aleatorio(X, y, arvores, argumentos.repeticoes))

    titulo("2. BLOCOS POR MUNICÍPIO")
    print("Cada cidade fica inteira de um lado. Testa cidade nunca vista.\n")
    resultados.append(kfold_por_municipio(X, y, dados["codigo_ibge"], arvores))

    titulo("3. BLOCOS POR ESTADO")
    print("UFs inteiras fora do treino. O bloco espacial mais largo.\n")
    resultados.append(kfold_por_uf(X, y, dados["uf"], arvores))

    titulo("4. TEMPORAL — janela expansiva (a do projeto)")
    print("Treina no passado, testa no futuro.\n")
    resultados.append(walk_forward(X, y, dados["ano"], arvores))

    # --- Tabela comparativa ------------------------------------------------
    titulo("RESULTADO")
    print(f"{'estratégia':<34}{'balanceada':>16}{'F1 macro':>15}{'risco alto':>15}")
    print("-" * 80)
    for r in resultados:
        print(f"{r['estrategia']:<34}"
              f"{r['balanceada_mean']:>10.1%} ±{r['balanceada_std']:>4.1%}"
              f"{r['f1_macro_mean']:>9.3f} ±{r['f1_macro_std']:.3f}"
              f"{r['recall_alto_mean']:>9.1%} ±{r['recall_alto_std']:>4.1%}")

    aleatoria = resultados[0]["balanceada_mean"]
    temporal = resultados[3]["balanceada_mean"]
    por_municipio = resultados[1]["balanceada_mean"]

    print(f"\nDistância entre a aleatória e a temporal: "
          f"{aleatoria - temporal:+.1%}")
    print(f"Distância entre a aleatória e os blocos por município: "
          f"{aleatoria - por_municipio:+.1%}")

    # --- Diagnóstico -------------------------------------------------------
    titulo("DIAGNÓSTICO: o modelo está decorando o município?")
    print("Mesmo modelo, dois testes do mesmo tamanho.\n")
    memorizacao = teste_de_memorizacao(X, y, dados["codigo_ibge"], arvores)

    print(f"  cidades no treino: {memorizacao['municipios_no_treino']:,} · "
          f"cidades novas: {memorizacao['municipios_novos']:,} · "
          f"{memorizacao['n_por_grupo']:,} linhas em cada teste\n")
    print(f"  {'':<24}{'balanceada':>13}{'F1 macro':>12}{'risco alto':>13}")
    for rotulo, chave in [("cidade vista no treino", "mesma_cidade"),
                          ("cidade nunca vista", "cidade_nova")]:
        m = memorizacao[chave]
        print(f"  {rotulo:<24}{m['balanceada']:>12.1%}{m['f1_macro']:>12.3f}"
              f"{m['recall_alto']:>13.1%}")

    queda = memorizacao["queda_balanceada"]
    print(f"\n  Queda ao mudar para cidade nova: {queda:+.1%}")
    if queda > 0.03:
        print("  >> O modelo se apoia na identidade do município. A validação")
        print("     aleatória, que sempre testa em cidade já vista, informa um")
        print("     número que não se repete em cidade nova.")
    else:
        print("  >> A queda é pequena: o modelo generaliza para cidade nova, e")
        print("     não está apenas decorando quais cidades são perigosas.")

    # --- Gravação ----------------------------------------------------------
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "comparacao_validacao.json"
    saida.write_text(json.dumps({
        "linhas": int(len(dados)),
        "municipios": int(dados["codigo_ibge"].nunique()),
        "arvores": arvores,
        "estrategias": resultados,
        "teste_de_memorizacao": memorizacao,
        "referencias": [
            "Roberts et al. (2017) Ecography 40:913-929",
            "Bergmeir, Hyndman & Koo (2018) Comput Stat Data Anal 120:70-83",
            "Cawley & Talbot (2010) JMLR 11:2079-2107",
        ],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nResultado salvo em {saida.relative_to(RAIZ)}")
    print(f"Tempo total: {(time.time() - inicio) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
