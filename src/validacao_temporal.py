"""
Validação temporal — o método correto para dados que têm tempo.

O problema com a validação cruzada comum
----------------------------------------
`StratifiedKFold` e `train_test_split` sorteiam as linhas. Numa base com
tempo, isso põe meses de 2024 no treino e meses de 2015 no teste: o modelo
usa o futuro para prever o passado. O número sai alto e não se sustenta.

O que este módulo faz
---------------------
**Validação walk-forward com janela expansiva.** O modelo é treinado com tudo
até um ano e avaliado no ano seguinte; depois esse ano entra no treino e o
processo se repete:

    treino 2010–2017  ->  testa 2018
    treino 2010–2018  ->  testa 2019
    treino 2010–2019  ->  testa 2020
    ...                   até o último ano

É exatamente como o sistema seria usado: em janeiro de 2026, só existe o que
aconteceu até dezembro de 2025. Cada ano vira um teste independente, e o
desvio-padrão entre eles mostra se o desempenho é estável ou depende de sorte.

Por que também existe um conjunto de validação separado
-------------------------------------------------------
Escolher hiperparâmetros olhando o conjunto de teste contamina o resultado:
o número final passa a medir "o melhor que consegui naquele teste", não o que
o modelo faria em dados novos. Por isso a base é dividida em TRÊS:

    treino     -> ajusta o modelo
    validação  -> escolhe os hiperparâmetros
    teste      -> tocado UMA vez, no fim, e só para relatar

Todas as três divisões são feitas por ano, nunca por sorteio.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, recall_score

from src import esquema


def gerar_janelas(anos: pd.Series, anos_minimos_treino: int = 8,
                  maximo_janelas: int | None = None) -> list[tuple[int, int]]:
    """
    Monta os pares (último ano de treino, ano de teste) da janela expansiva.

    `anos_minimos_treino` evita avaliar um modelo treinado com pouca história,
    o que produziria um resultado ruim que não diz nada sobre o método.
    """
    disponiveis = sorted(anos.unique())
    if len(disponiveis) <= anos_minimos_treino:
        raise ValueError(
            f"são necessários mais de {anos_minimos_treino} anos para a "
            f"validação temporal; a base tem {len(disponiveis)}."
        )

    janelas = [
        (disponiveis[i - 1], disponiveis[i])
        for i in range(anos_minimos_treino, len(disponiveis))
    ]

    if maximo_janelas:
        janelas = janelas[-maximo_janelas:]
    return janelas


def _medir(y_real, y_previsto) -> dict:
    return {
        "balanceada": float(balanced_accuracy_score(y_real, y_previsto)),
        "f1_macro": float(f1_score(y_real, y_previsto, average="macro")),
        "recall_alto": float(
            recall_score(y_real, y_previsto, labels=["alto"], average="macro",
                         zero_division=0)
        ),
    }


def validar_walk_forward(criar_modelo, X: pd.DataFrame, y: pd.Series,
                         anos: pd.Series, janelas: list[tuple[int, int]],
                         ao_terminar_janela=None) -> dict:
    """
    Roda a validação walk-forward.

    `criar_modelo` é uma função sem argumentos que devolve um modelo novo —
    precisa ser novo a cada janela, senão o modelo carregaria o que aprendeu
    do futuro para a janela anterior.
    """
    resultados = []

    for ano_treino_final, ano_teste in janelas:
        treino = anos <= ano_treino_final
        teste = anos == ano_teste

        if teste.sum() == 0 or treino.sum() == 0:
            continue
        if y[treino].nunique() < 2:
            continue

        modelo = criar_modelo()
        modelo.fit(X[treino], y[treino])
        previsao = modelo.predict(X[teste])

        medida = _medir(y[teste], previsao)
        medida.update({
            "ano_teste": int(ano_teste),
            "treino_ate": int(ano_treino_final),
            "linhas_treino": int(treino.sum()),
            "linhas_teste": int(teste.sum()),
        })
        resultados.append(medida)

        if ao_terminar_janela:
            ao_terminar_janela(medida)

    if not resultados:
        raise ValueError("nenhuma janela pôde ser avaliada.")

    tabela = pd.DataFrame(resultados)
    resumo = {
        "janelas": resultados,
        "n_janelas": len(resultados),
        "periodo_testado": f"{tabela['ano_teste'].min()}–{tabela['ano_teste'].max()}",
    }
    for metrica in ("balanceada", "f1_macro", "recall_alto"):
        resumo[f"{metrica}_media"] = float(tabela[metrica].mean())
        resumo[f"{metrica}_desvio"] = float(tabela[metrica].std())
        resumo[f"{metrica}_pior"] = float(tabela[metrica].min())

    return resumo


def dividir_em_tres(dados: pd.DataFrame, ano_validacao: int, ano_teste: int
                    ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Máscaras booleanas de treino, validação e teste, cortadas por ano.

        treino    : anos  <  ano_validacao
        validação : ano_validacao <= anos < ano_teste
        teste     : anos  >= ano_teste
    """
    if not ano_validacao < ano_teste:
        raise ValueError(
            f"o ano de validação ({ano_validacao}) precisa ser anterior ao "
            f"ano de teste ({ano_teste})."
        )

    anos = dados["ano"]
    treino = anos < ano_validacao
    validacao = (anos >= ano_validacao) & (anos < ano_teste)
    teste = anos >= ano_teste

    for nome, mascara in (("treino", treino), ("validação", validacao),
                          ("teste", teste)):
        if mascara.sum() == 0:
            raise ValueError(
                f"o conjunto de {nome} ficou vazio. Ajuste os anos de corte."
            )

    return treino, validacao, teste


def escolher_hiperparametros(criar_modelo, candidatos: list[dict],
                             X: pd.DataFrame, y: pd.Series,
                             treino: pd.Series, validacao: pd.Series,
                             metrica: str = "f1_macro",
                             tolerancia: float = 0.01,
                             complexidade=None,
                             ao_testar=None) -> tuple[dict, list[dict]]:
    """
    Escolhe os hiperparâmetros usando APENAS o conjunto de validação.

    O conjunto de teste não é tocado aqui — é isso que mantém o número final
    honesto. Testar dez configurações no teste e reportar a melhor equivale a
    escolher a régua depois de ver o resultado.

    **Regra da parcimônia.** Pegar sempre o maior número seria ingênuo:
    diferenças de meio ponto entre candidatos são ruído da amostra, não
    superioridade real. Entre os candidatos que ficam a menos de `tolerancia`
    do melhor, vence o mais SIMPLES. Modelo simples generaliza melhor para
    dados que ainda não existem, e aqui também gera um arquivo menor — o que
    importa num projeto que precisa rodar em outro computador.

    É a mesma ideia da "regra de um erro-padrão", comum em seleção de modelos.
    """
    historico = []

    for parametros in candidatos:
        modelo = criar_modelo(**parametros)
        modelo.fit(X[treino], y[treino])
        medida = _medir(y[validacao], modelo.predict(X[validacao]))
        medida["parametros"] = parametros
        historico.append(medida)

        if ao_testar:
            ao_testar(medida)

    melhor_nota = max(item[metrica] for item in historico)
    empatados = [
        item for item in historico if item[metrica] >= melhor_nota - tolerancia
    ]

    if complexidade is None:
        escolhido = max(empatados, key=lambda item: item[metrica])
    else:
        escolhido = min(empatados, key=lambda item: complexidade(item["parametros"]))

    escolhido["escolhido_por_parcimonia"] = escolhido[metrica] < melhor_nota
    return escolhido["parametros"], historico


def formatar_walk_forward(resumo: dict) -> str:
    """Relatório em texto da validação walk-forward."""
    linhas = [
        f"Janela expansiva: {resumo['n_janelas']} anos testados "
        f"({resumo['periodo_testado']})",
        "",
        f"{'treino até':>11}{'testa':>7}{'linhas':>10}"
        f"{'balanceada':>13}{'F1 macro':>11}{'risco alto':>12}",
        "-" * 64,
    ]

    for janela in resumo["janelas"]:
        linhas.append(
            f"{janela['treino_ate']:>11}{janela['ano_teste']:>7}"
            f"{janela['linhas_teste']:>10,}"
            f"{janela['balanceada']:>12.1%}{janela['f1_macro']:>11.3f}"
            f"{janela['recall_alto']:>12.1%}"
        )

    linhas += [
        "-" * 64,
        f"{'média':>18}{'':>10}"
        f"{resumo['balanceada_media']:>12.1%}"
        f"{resumo['f1_macro_media']:>11.3f}"
        f"{resumo['recall_alto_media']:>12.1%}",
        f"{'desvio-padrão':>18}{'':>10}"
        f"{resumo['balanceada_desvio']:>12.1%}"
        f"{resumo['f1_macro_desvio']:>11.3f}"
        f"{resumo['recall_alto_desvio']:>12.1%}",
        f"{'pior ano':>18}{'':>10}"
        f"{resumo['balanceada_pior']:>12.1%}"
        f"{resumo['f1_macro_pior']:>11.3f}"
        f"{resumo['recall_alto_pior']:>12.1%}",
        "",
    ]

    if resumo["balanceada_desvio"] > 0.05:
        linhas.append(
            "Variação alta entre os anos: o desempenho depende muito de qual "
            "período é testado."
        )
    else:
        linhas.append(
            "Variação baixa entre os anos: o desempenho é estável ao longo do "
            "tempo, e não fruto de um período favorável."
        )

    return "\n".join(linhas)
