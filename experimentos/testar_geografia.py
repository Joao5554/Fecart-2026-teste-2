"""
Geografia estática melhora a previsão?

A hipótese: cidade baixa, plana e à beira de rio grande alaga mais; cidade de
encosta íngreme escorrega mais. Se for verdade e o modelo ainda não souber
disso, acrescentar altitude, declividade, área e distância do rio deve render
acurácia.

Há um motivo forte para desconfiar, e ele já apareceu duas vezes neste
projeto (com a chuva do INMET, com a calibração): **a informação pode já estar
lá por outro caminho**. O histórico de ocorrências de um município É, em boa
parte, a consequência da geografia dele. Um município que alagou trinta vezes
já contou ao modelo que fica perto de um rio.

Há também um motivo forte para tentar, e ele é novo: desde `src/atlas._ancora`,
consultar um mês futuro congela o histórico no fim da base. Geografia não
congela — ela vale igual em 2025 e em 2027. Se ela ajudar, ajuda exatamente
onde o resto do modelo está mais cego.

Protocolo — o mesmo do resto do projeto:
    janela expansiva, treina até um ano e testa no seguinte, 8 anos
    (2018–2025), as duas variantes nas MESMAS janelas e nas mesmas linhas.
    Teste t pareado sobre as diferenças ano a ano.

Como rodar (a partir da raiz do projeto):
    python experimentos/testar_geografia.py

Nada aqui altera o modelo em produção.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import caracteristicas, esquema, validacao_temporal  # noqa: E402
from src.carregar import carregar_dados  # noqa: E402
from treinamento.treinar_modelo import (  # noqa: E402
    CONFIG_BOOSTING, ajustar, construir_modelo,
)
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
ARQUIVO_GEOGRAFIA = RAIZ / "dados" / "geografia_municipios.csv"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

SEMENTE = 42

# As colunas novas, todas estáticas: não mudam de um mês para o outro.
GEOGRAFIA = [
    "altitude_media_m",
    "altitude_minima_m",
    "amplitude_altitude_m",
    "declividade_m_por_km",
    "area_km2",
    "distancia_rio_km",
    "distancia_rio_grande_km",
    "latitude",
    "longitude",
]


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def preprocessador(numericas: list[str], categoricas: list[str]) -> ColumnTransformer:
    """
    Igual ao de `src/caracteristicas`, mas com a lista de colunas explícita.

    O do projeto lê as colunas do esquema, e o esquema é justamente o que este
    experimento NÃO pode tocar enquanto a resposta não estiver medida.
    """
    numerico = Pipeline([
        ("imputacao", SimpleImputer(strategy="median", keep_empty_features=True)),
    ])
    categorico = Pipeline([
        ("imputacao", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return ColumnTransformer(
        transformers=[("num", numerico, numericas),
                      ("cat", categorico, categoricas)],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def criar_boosting(numericas: list[str], categoricas: list[str]):
    """A mesma configuração que está em produção, com outra lista de colunas."""
    def criar():
        return Pipeline([
            ("preparacao", preprocessador(numericas, categoricas)),
            ("boosting", HistGradientBoostingClassifier(
                random_state=SEMENTE, **CONFIG_BOOSTING
            )),
        ])
    return criar


def caminhar(criar, X, y, anos, janelas):
    """
    Janela expansiva que guarda a previsão LINHA A LINHA.

    `validacao_temporal.validar_walk_forward` devolve só a média de cada ano, e
    aqui é preciso mais: a pergunta interessante não é "melhorou?", e sim
    "melhorou ONDE?". Guardar a previsão de cada linha permite separar depois
    os municípios com muito histórico dos que quase não têm — que é justamente
    onde a geografia teria alguma chance de dizer algo novo.
    """
    previsoes = pd.Series(index=y.index, dtype=object)
    por_ano = []

    for ate, ano_teste in janelas:
        treino = anos <= ate
        teste = anos == ano_teste
        modelo = ajustar(criar(), X[treino], y[treino])
        previsoes[teste] = modelo.predict(X[teste])

        medida = validacao_temporal._medir(y[teste], previsoes[teste])
        medida["ano_teste"] = int(ano_teste)
        por_ano.append(medida)
        print(f"  {ano_teste}: balanceada {medida['balanceada']:.1%}  "
              f"F1 {medida['f1_macro']:.3f}  "
              f"risco alto {medida['recall_alto']:.1%}", flush=True)

    return previsoes, por_ano


def faixas_de_historico(dados: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Separa as linhas por quanto histórico o modelo tinha sobre aquele par.

    É o teste da hipótese na sua forma mais forte: se a geografia serve para
    alguma coisa, é para falar de município sobre o qual o histórico se cala.
    """
    total = dados["ocorrencias_total_historico"]
    return {
        "sem histórico (0)": total == 0,
        "pouco (1 a 2)": (total >= 1) & (total <= 2),
        "médio (3 a 9)": (total >= 3) & (total <= 9),
        "muito (10+)": total >= 10,
    }


def teste_pareado(com: list[float], sem: list[float]) -> dict:
    from scipy import stats

    diferencas = np.array(com) - np.array(sem)
    t, p = stats.ttest_rel(com, sem)
    return {
        "diferenca_media": float(diferencas.mean()),
        "diferenca_desvio": float(diferencas.std(ddof=1)),
        "vitorias": int((diferencas > 0).sum()),
        "anos": len(diferencas),
        "t": float(t),
        "p_unilateral": float(p / 2 if t > 0 else 1 - p / 2),
    }


def main() -> int:
    titulo("GEOGRAFIA ESTÁTICA MELHORA A PREVISÃO?")

    if not ARQUIVO_GEOGRAFIA.exists():
        print(f"Falta {ARQUIVO_GEOGRAFIA.name}. "
              f"Rode: python dados/preparar_geografia.py")
        return 1

    dados = carregar_dados(ARQUIVO_DADOS)
    geografia = pd.read_csv(ARQUIVO_GEOGRAFIA)

    antes = len(dados)
    dados = dados.merge(geografia, on="codigo_ibge", how="left")
    assert len(dados) == antes, "o merge duplicou linhas"

    sem_geografia = dados["altitude_media_m"].isna().mean()
    print(f"{len(dados):,} linhas | {dados['codigo_ibge'].nunique():,} municípios")
    print(f"Linhas sem geografia casada: {sem_geografia:.2%}")
    print(f"Colunas novas: {len(GEOGRAFIA)}")

    dados = caracteristicas.adicionar_derivadas(dados)
    y = dados[esquema.COLUNA_ALVO]
    anos = dados["ano"]

    numericas_base = list(esquema.COLUNAS_MODELO_NUMERICAS)
    categoricas = list(esquema.COLUNAS_MODELO_CATEGORICAS)

    variantes = {
        "sem geografia": numericas_base,
        "com geografia": numericas_base + GEOGRAFIA,
    }

    janelas = validacao_temporal.gerar_janelas(anos)
    print(f"\n{len(janelas)} janelas: treina até um ano, testa no seguinte.")

    previsoes, por_ano = {}, {}
    for nome, numericas in variantes.items():
        print(f"\n--- {nome} ({len(numericas)} numéricas) ---", flush=True)
        X = dados[numericas + categoricas]
        previsoes[nome], por_ano[nome] = caminhar(
            criar_boosting(numericas, categoricas), X, y, anos, janelas
        )

    titulo("ANO A ANO")
    sem, com = por_ano["sem geografia"], por_ano["com geografia"]

    print(f"{'ano':>6}{'sem geografia':>16}{'com geografia':>16}{'diferença':>12}")
    print("-" * 50)
    for a, b in zip(sem, com):
        print(f"{a['ano_teste']:>6}{a['balanceada']:>15.1%}"
              f"{b['balanceada']:>16.1%}"
              f"{b['balanceada'] - a['balanceada']:>+12.1%}")

    print("-" * 50)
    medias = {nome: float(np.mean([j["balanceada"] for j in lista]))
              for nome, lista in por_ano.items()}
    print(f"{'média':>6}{medias['sem geografia']:>15.1%}"
          f"{medias['com geografia']:>16.1%}")

    titulo("VEREDITO GERAL")
    prova = teste_pareado([j["balanceada"] for j in com],
                          [j["balanceada"] for j in sem])
    print(f"  diferença média:  {prova['diferenca_media']:+.2%} "
          f"(desvio {prova['diferenca_desvio']:.2%})")
    print(f"  anos em que ajudou: {prova['vitorias']} de {prova['anos']}")
    print(f"  teste t pareado:  t={prova['t']:+.2f}, "
          f"p={prova['p_unilateral']:.3f} (unilateral)")

    # Mesmo critério das outras seções: maioria clara dos anos E média
    # positiva. Cinco de oito é praticamente cara ou coroa.
    aprovado = prova["vitorias"] >= 6 and prova["diferenca_media"] > 0
    print(f"\n  {'APROVADO' if aprovado else 'REPROVADO'} "
          f"(exigido: 6 de {prova['anos']} anos e média positiva)")

    # ----------------------------------------------------------------------
    titulo("ONDE A GEOGRAFIA TERIA ALGUMA CHANCE: LINHAS SEM HISTÓRICO")
    print("A hipótese em pé: o histórico de um município já É a consequência")
    print("da geografia dele. Se for isso, a geografia só deveria ajudar onde")
    print("o histórico se cala.\n")

    avaliadas = previsoes["sem geografia"].notna()
    testadas = dados[avaliadas]
    y_teste = y[avaliadas]

    print(f"{'faixa de histórico':<22}{'linhas':>9}{'sem geo':>10}"
          f"{'com geo':>10}{'diferença':>12}")
    print("-" * 63)

    por_faixa = {}
    for rotulo, mascara in faixas_de_historico(testadas).items():
        if mascara.sum() < 100 or y_teste[mascara.to_numpy()].nunique() < 2:
            print(f"  {rotulo:<20}{int(mascara.sum()):>9,}   "
                  f"poucas linhas para medir")
            continue

        indices = testadas.index[mascara]
        a = validacao_temporal._medir(y[indices],
                                      previsoes["sem geografia"][indices])
        b = validacao_temporal._medir(y[indices],
                                      previsoes["com geografia"][indices])
        por_faixa[rotulo] = {"linhas": int(len(indices)),
                             "sem_geografia": a, "com_geografia": b}
        print(f"  {rotulo:<20}{len(indices):>9,}{a['balanceada']:>10.1%}"
              f"{b['balanceada']:>10.1%}"
              f"{b['balanceada'] - a['balanceada']:>+12.1%}")

    print()
    if aprovado:
        print("  A geografia ajudou de forma consistente.")
    else:
        print("  No conjunto todo, a geografia NÃO ajudou.")
        print("  O histórico de ocorrências de um município já é, em boa parte,")
        print("  a consequência da geografia dele — e o modelo já tinha esse")
        print("  histórico. É o mesmo motivo pelo qual a chuva do INMET também")
        print("  não rendeu: a informação já estava lá, por outro caminho.")

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "geografia.json"
    saida.write_text(json.dumps({
        "colunas_novas": GEOGRAFIA,
        "linhas": int(len(dados)),
        "por_ano": por_ano,
        "teste_pareado": prova,
        "aprovado": bool(aprovado),
        "por_faixa_de_historico": por_faixa,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
