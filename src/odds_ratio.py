"""
Odds ratio (razão de chances) das variáveis do modelo.

Por que este arquivo existe
---------------------------
O Random Forest prevê bem, mas explica mal. A "importância" que ele devolve
diz *quanto* uma variável ajudou a separar os casos — não diz a **direção**
(aumenta ou diminui o risco?) nem o **tamanho** do efeito.

O odds ratio responde as duas coisas em um número só:

    OR = 2,0  -> a chance DOBRA
    OR = 1,0  -> a variável não altera a chance
    OR = 0,5  -> a chance cai pela metade

Ele vem de uma **regressão logística**, ajustada aqui sobre os mesmos dados do
Random Forest. São dois modelos com papéis diferentes, e isso é proposital:

    Random Forest       -> faz a previsão (é o que a API usa)
    Regressão logística -> explica o efeito de cada variável (é o que se
                           apresenta e se discute)

Cuidados estatísticos aplicados
-------------------------------
1. **Multicolinearidade.** `ocorrencias_12m`, `_24m`, `_60m` e o total são
   quase a mesma informação (correlação de até 0,88). Numa regressão isso
   infla os erros-padrão e faz o coeficiente de uma variável "roubar" o da
   outra — o OR sai instável e às vezes com o sinal invertido. O VIF (fator
   de inflação de variância) mede isso, e as variáveis acima do limite são
   removidas, uma por vez, começando pela pior.

2. **Escala.** As variáveis têm unidades incomparáveis (meses, pessoas,
   reais). Todas são padronizadas, então o OR lê-se sempre como
   "por 1 desvio-padrão a mais".

3. **Sem regularização.** A regressão usada para inferência roda praticamente
   sem penalidade (C alto). Penalidade encolhe coeficientes de propósito, o
   que é bom para prever e ruim para estimar efeito.

4. **Incerteza declarada.** Cada OR vem com intervalo de confiança de 95% e
   p-valor. OR cujo intervalo cruza o 1,0 não é distinguível de "sem efeito",
   e isso fica marcado no resultado.
"""

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src import esquema

# Acima deste valor, a variável é considerada redundante com as demais.
# 10 é o limite mais citado na literatura aplicada; 5 é a versão conservadora.
LIMITE_VIF = 10.0

# `mes` fica de fora: é cíclico (dezembro é vizinho de janeiro), e um
# coeficiente linear sobre ele não teria interpretação. A sazonalidade entra
# pela variável `ocorrencias_mesmo_mes_historico`.
#
# As janelas cumulativas de 24 e 60 meses também saem, substituídas pelas
# faixas disjuntas montadas em JANELAS_DISJUNTAS (ver abaixo).
NUMERICAS_EXCLUIDAS = ("mes", "ocorrencias_24m", "ocorrencias_60m")

# As contagens do modelo são ANINHADAS: a janela de 60 meses contém a de 24,
# que contém a de 12. Colocar as três na mesma regressão é um erro clássico —
# o coeficiente de uma passa a significar "o que sobra depois de descontar as
# outras", e o sinal se inverte. Foi exatamente o que aconteceu aqui: as
# ocorrências dos últimos 12 meses apareciam como se REDUZISSEM o risco.
#
# A correção é usar faixas que não se sobrepõem. Cada uma passa a responder
# uma pergunta própria: o que houve no último ano, no ano anterior a esse, e
# nos três anos antes disso.
JANELAS_DISJUNTAS = {
    "ocorrencias_13_a_24m": ("ocorrencias_24m", "ocorrencias_12m"),
    "ocorrencias_25_a_60m": ("ocorrencias_60m", "ocorrencias_24m"),
}

# `uf` tem 27 níveis e é redundante com `regiao`; usar as duas produziria
# dezenas de coeficientes instáveis. Fica a região, que é mais legível.
CATEGORICAS_USADAS = ("regiao", "grupo_desastre")

ANALISES = {
    "ocorrencia": {
        "descricao": "Chance de haver algum desastre no mês (médio ou alto)",
        "positivo": lambda alvo: alvo != "baixo",
        "nome_evento": "houve desastre",
    },
    "gravidade": {
        "descricao": "Chance de o desastre ser grave (risco alto)",
        "positivo": lambda alvo: alvo == "alto",
        "nome_evento": "risco alto",
    },
}


def _variaveis_numericas() -> list[str]:
    return [c for c in esquema.COLUNAS_NUMERICAS if c not in NUMERICAS_EXCLUIDAS]


def calcular_vif(X: pd.DataFrame) -> pd.Series:
    """
    Fator de inflação de variância de cada coluna.

    VIF_j = 1 / (1 - R²_j), onde R²_j vem de regredir a coluna j contra todas
    as outras. Um VIF de 10 significa que o erro-padrão daquele coeficiente
    está 3,2 vezes maior (raiz de 10) do que estaria sem a redundância.

    O cálculo usa a inversa da matriz de correlação, que dá o mesmo resultado
    das N regressões auxiliares e é muito mais rápido.
    """
    # Colunas constantes fazem o desvio-padrão ser zero e a correlação virar
    # NaN. Isso é esperado (acontece com uma categoria que só tem um valor na
    # amostra), então o aviso do numpy é silenciado e o NaN vira zero.
    constantes = X.std(axis=0) == 0
    with np.errstate(invalid="ignore", divide="ignore"):
        correlacao = np.corrcoef(X.to_numpy(), rowvar=False)

    correlacao = np.nan_to_num(correlacao, nan=0.0)
    np.fill_diagonal(correlacao, 1.0)

    try:
        inversa = np.linalg.inv(correlacao)
    except np.linalg.LinAlgError:
        inversa = np.linalg.pinv(correlacao)

    vif = pd.Series(np.diag(inversa), index=X.columns).clip(lower=1.0)
    vif[constantes.to_numpy()] = np.inf
    return vif


def selecionar_sem_colinearidade(
    X: pd.DataFrame, limite: float = LIMITE_VIF
) -> tuple[list[str], list[tuple[str, float]]]:
    """
    Remove variáveis redundantes, uma de cada vez.

    A cada rodada tira a de maior VIF e recalcula, porque remover uma variável
    costuma derrubar o VIF das outras. Devolve as colunas mantidas e o
    histórico do que saiu, para o relatório poder mostrar as decisões.
    """
    mantidas = list(X.columns)
    removidas: list[tuple[str, float]] = []

    while len(mantidas) > 1:
        vif = calcular_vif(X[mantidas])
        pior = vif.idxmax()
        if vif[pior] <= limite:
            break
        removidas.append((pior, float(vif[pior])))
        mantidas.remove(pior)

    return mantidas, removidas


def montar_matriz(dados: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Monta a matriz de variáveis explicativas da regressão.

    Numéricas entram padronizadas; categóricas viram indicadoras com uma
    categoria de referência descartada (`drop_first`), o que evita a
    colinearidade perfeita entre as colunas indicadoras.
    """
    X = dados[_variaveis_numericas()].astype(float).copy()

    # Faixas disjuntas no lugar das janelas aninhadas (ver JANELAS_DISJUNTAS).
    for nome, (maior, menor) in JANELAS_DISJUNTAS.items():
        if maior in dados.columns and menor in dados.columns:
            X[nome] = (dados[maior] - dados[menor]).clip(lower=0).astype(float)

    numericas = list(X.columns)
    escalador = StandardScaler()
    X[numericas] = escalador.fit_transform(X[numericas])

    for coluna in CATEGORICAS_USADAS:
        if coluna in dados.columns:
            indicadoras = pd.get_dummies(
                dados[coluna], prefix=coluna, drop_first=True, dtype=float
            )
            X = pd.concat([X, indicadoras], axis=1)

    desvios = pd.Series(escalador.scale_, index=numericas)
    return X, desvios


def _ajustar_com_erros_padrao(X: np.ndarray, y: np.ndarray):
    """
    Ajusta a regressão logística e devolve coeficientes e erros-padrão.

    O scikit-learn não expõe erro-padrão, então ele é obtido da matriz de
    informação de Fisher: cov = (Xᵀ W X)⁻¹, com W = p(1-p). É a mesma conta
    que um pacote estatístico faria.
    """
    modelo = LogisticRegression(
        C=1e6,            # penalidade desprezível: queremos o efeito, não previsão
        max_iter=2000,
        solver="lbfgs",
    )
    modelo.fit(X, y)

    coeficientes = modelo.coef_[0]
    probabilidades = modelo.predict_proba(X)[:, 1]
    pesos = probabilidades * (1.0 - probabilidades)

    # Coluna de 1s para o intercepto entrar na matriz de covariância.
    Xi = np.column_stack([np.ones(len(X)), X])
    informacao = Xi.T @ (Xi * pesos[:, None])

    try:
        covariancia = np.linalg.inv(informacao)
    except np.linalg.LinAlgError:
        covariancia = np.linalg.pinv(informacao)

    erros = np.sqrt(np.clip(np.diag(covariancia)[1:], 0, None))
    return modelo, coeficientes, erros


def calcular(dados: pd.DataFrame, analise: str = "gravidade",
             limite_vif: float = LIMITE_VIF) -> dict:
    """
    Calcula os odds ratios de uma das análises definidas em ANALISES.

    Devolve um dicionário com a tabela de resultados, as variáveis removidas
    por colinearidade e a qualidade do ajuste (AUC) — sem ela não dá para
    saber se os ORs vêm de um modelo que descreve os dados de forma razoável.
    """
    if analise not in ANALISES:
        raise ValueError(
            f"análise '{analise}' desconhecida. Use: {', '.join(ANALISES)}"
        )

    configuracao = ANALISES[analise]
    y = configuracao["positivo"](dados[esquema.COLUNA_ALVO]).astype(int).to_numpy()

    if len(np.unique(y)) < 2:
        raise ValueError(
            f"a análise '{analise}' não tem os dois desfechos nestes dados."
        )

    X, desvios = montar_matriz(dados)
    mantidas, removidas = selecionar_sem_colinearidade(X, limite_vif)
    X = X[mantidas]

    modelo, coeficientes, erros = _ajustar_com_erros_padrao(X.to_numpy(), y)

    razao_z = np.divide(coeficientes, erros, out=np.zeros_like(coeficientes),
                        where=erros > 0)
    p_valores = 2.0 * (1.0 - stats.norm.cdf(np.abs(razao_z)))

    # Quando uma categoria é rara e prevê o desfecho quase perfeitamente
    # ("separação"), o coeficiente tende ao infinito e o odds ratio estoura.
    # O número que sai (OR de milhões, intervalo de zero a infinito) parece
    # um efeito gigantesco, mas significa apenas "não há dados suficientes".
    # O expoente é limitado e a linha fica marcada como não confiável.
    LIMITE_EXPOENTE = 20.0
    instavel = (np.abs(coeficientes) > LIMITE_EXPOENTE) | (erros > LIMITE_EXPOENTE)

    def exponencial_segura(valores):
        return np.exp(np.clip(valores, -LIMITE_EXPOENTE, LIMITE_EXPOENTE))

    tabela = pd.DataFrame({
        "variavel": mantidas,
        "coeficiente": coeficientes,
        "erro_padrao": erros,
        "odds_ratio": exponencial_segura(coeficientes),
        "ic95_inferior": exponencial_segura(coeficientes - 1.96 * erros),
        "ic95_superior": exponencial_segura(coeficientes + 1.96 * erros),
        "p_valor": p_valores,
        "confiavel": ~instavel,
    })

    # Um OR só é distinguível de "sem efeito" quando o intervalo não cruza 1 —
    # e quando a estimativa é estável o bastante para ser levada a sério.
    tabela["significativo"] = (
        ((tabela["ic95_inferior"] > 1.0) | (tabela["ic95_superior"] < 1.0))
        & tabela["confiavel"]
    )
    # A leitura natural é "quanto muda a chance", em qualquer direção: um OR de
    # 0,5 é tão forte quanto um de 2,0. Ordenar pelo efeito absoluto coloca os
    # dois no topo.
    tabela["forca"] = np.abs(np.log(tabela["odds_ratio"]))
    tabela = tabela.sort_values("forca", ascending=False).reset_index(drop=True)

    from sklearn.metrics import roc_auc_score
    auc = float(roc_auc_score(y, modelo.predict_proba(X.to_numpy())[:, 1]))

    return {
        "analise": analise,
        "descricao": configuracao["descricao"],
        "nome_evento": configuracao["nome_evento"],
        "n_amostras": int(len(dados)),
        "n_eventos": int(y.sum()),
        "taxa_evento": float(y.mean()),
        "auc": auc,
        "limite_vif": limite_vif,
        "removidas_por_colinearidade": [
            {"variavel": nome, "vif": round(valor, 1)} for nome, valor in removidas
        ],
        "desvios_padrao": {
            nome: float(desvios[nome]) for nome in desvios.index if nome in mantidas
        },
        "tabela": tabela,
    }


def interpretar(linha: pd.Series, desvios: dict) -> str:
    """Traduz uma linha da tabela em uma frase em português."""
    razao = linha["odds_ratio"]
    nome = linha["variavel"]

    if not linha["significativo"]:
        return f"{nome}: sem efeito distinguível de zero (p = {linha['p_valor']:.3f})"

    if razao >= 1:
        efeito = f"multiplica a chance por {razao:.2f}"
    else:
        efeito = f"reduz a chance para {razao:.2f}x (queda de {(1 - razao) * 100:.0f}%)"

    unidade = desvios.get(nome)
    referencia = (
        f"a cada {unidade:.1f} unidade(s) a mais" if unidade
        else "em relação à categoria de referência"
    )
    return f"{nome}: {efeito} {referencia}"


def formatar_relatorio(resultado: dict, quantidade: int = 12) -> str:
    """Texto pronto para imprimir no terminal ou colar na apresentação."""
    linhas = [
        f"ODDS RATIO — {resultado['descricao']}",
        "",
        f"Evento analisado: {resultado['nome_evento']}",
        f"{resultado['n_eventos']:,} de {resultado['n_amostras']:,} linhas "
        f"({resultado['taxa_evento']:.1%})",
        f"AUC da regressão logística: {resultado['auc']:.3f}",
    ]

    if resultado["removidas_por_colinearidade"]:
        removidas = ", ".join(
            f"{r['variavel']} (VIF {r['vif']:.0f})"
            for r in resultado["removidas_por_colinearidade"]
        )
        linhas += [
            "",
            f"Removidas por redundância (VIF > {resultado['limite_vif']:.0f}): {removidas}",
        ]

    linhas += [
        "",
        "OR > 1 aumenta a chance | OR < 1 reduz | valores por desvio-padrão",
        "",
        f"{'variável':<34}{'OR':>7}{'IC 95%':>18}{'p':>9}",
        "-" * 70,
    ]

    for _, linha in resultado["tabela"].head(quantidade).iterrows():
        intervalo = f"{linha['ic95_inferior']:.2f} – {linha['ic95_superior']:.2f}"
        p = "<0,001" if linha["p_valor"] < 0.001 else f"{linha['p_valor']:.3f}"
        if not linha.get("confiavel", True):
            marca = "  (instável)"
        elif not linha["significativo"]:
            marca = "  (n.s.)"
        else:
            marca = ""
        linhas.append(
            f"{linha['variavel']:<34}{linha['odds_ratio']:>7.2f}{intervalo:>18}"
            f"{p:>9}{marca}"
        )

    linhas += [
        "",
        "n.s.     = não significativo: o intervalo de confiança inclui 1,0.",
        "instável = dados insuficientes para essa categoria; ignore o valor.",
    ]
    return "\n".join(linhas)


def para_json(resultado: dict, quantidade: int | None = None) -> dict:
    """Versão serializável, para gravar nos metadados e servir pela API."""
    tabela = resultado["tabela"]
    if quantidade:
        tabela = tabela.head(quantidade)

    return {
        "analise": resultado["analise"],
        "descricao": resultado["descricao"],
        "n_amostras": resultado["n_amostras"],
        "n_eventos": resultado["n_eventos"],
        "taxa_evento": round(resultado["taxa_evento"], 4),
        "auc": round(resultado["auc"], 4),
        "limite_vif": resultado["limite_vif"],
        "removidas_por_colinearidade": resultado["removidas_por_colinearidade"],
        "variaveis": [
            {
                "variavel": linha["variavel"],
                "odds_ratio": round(float(linha["odds_ratio"]), 4),
                "ic95_inferior": round(float(linha["ic95_inferior"]), 4),
                "ic95_superior": round(float(linha["ic95_superior"]), 4),
                "p_valor": float(f"{linha['p_valor']:.3g}"),
                "significativo": bool(linha["significativo"]),
                "confiavel": bool(linha.get("confiavel", True)),
            }
            for _, linha in tabela.iterrows()
        ],
    }
