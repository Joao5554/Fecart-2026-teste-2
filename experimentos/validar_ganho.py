"""
O ganho de +0,7% se repete, ou foi sorte de um ano só?

O experimento anterior (`melhorar_modelo.py`) mediu cada ideia UMA vez, num
único teste (2022–2025), e encontrou um único candidato com sinal positivo:
gradient boosting com limiar de decisão ajustado, +0,7 ponto de acurácia
balanceada. O próprio relatório avisou que esse número cabe dentro do desvio
entre anos (±4,9 pontos) e que não dava para confiar nele.

Confiar ou não é uma pergunta que se responde medindo várias vezes.

    Para cada ano Y de 2019 a 2024:
        treina   com tudo até Y-2
        valida   em Y-1      -> escolhe o limiar aqui, nunca no teste
        testa    em Y

Seis testes independentes, cada um com o mesmo protocolo do sistema real: só
passado no treino, e um ano inteiro que ninguém viu no teste. Se a vantagem
for real, ela aparece na maioria dos anos. Se for ruído, ela troca de lado.

A regra de decisão está escrita ANTES de rodar, para não virar "escolhi o que
deu melhor depois de ver":

    aplica-se a mudança no projeto apenas se ela vencer o Random Forest atual
    em pelo menos 4 dos 6 anos E a média da diferença for positiva.

Como rodar (a partir da raiz do projeto):
    python experimentos/validar_ganho.py
    python experimentos/validar_ganho.py --anos 2022 2023 2024   (mais rápido)

Nada aqui altera o modelo em produção: o script só lê `dados/dados.csv` e
grava um relatório em `experimentos/resultados/`.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import caracteristicas, esquema  # noqa: E402
from src.carregar import carregar_dados  # noqa: E402
from treinamento.treinar_modelo import construir_modelo  # noqa: E402

# Reaproveita as definições do estudo, em vez de reescrevê-las: assim a
# comparação usa exatamente o mesmo boosting e o mesmo ajuste de limiar que
# produziram o +0,7% — se o número mudar, mudou por causa do protocolo, não
# porque o código é outro.
import melhorar_modelo as estudo  # noqa: E402

ARQUIVO_DADOS = RAIZ / "dados" / "dados.csv"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

SEMENTE = 42

# Configuração do modelo que está em produção hoje (ver modelo/metadados.json).
# Fixar estes valores mantém a comparação limpa: o que muda de uma variante
# para outra é o algoritmo e o limiar, não a profundidade da árvore.
ARVORES = 100
PROFUNDIDADE = 20
FOLHA = 5

ANOS_PADRAO = [2019, 2020, 2021, 2022, 2023, 2024]

# Critério de aprovação, fixado antes da medição.
MINIMO_DE_VITORIAS = 4


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def avaliar_ano(dados, X, y, ano: int) -> dict:
    """
    Treina, escolhe o limiar e mede as quatro variantes para um ano de teste.

    Os dois modelos são ajustados uma única vez cada; as versões "com limiar"
    reaproveitam as mesmas probabilidades. Medir quatro variantes custa dois
    treinos, não quatro.
    """
    anos = dados["ano"]
    treino = anos <= ano - 2
    validacao = anos == ano - 1
    teste = anos == ano

    X_tr, y_tr = X[treino], y[treino]
    X_val, y_val = X[validacao], y[validacao]
    X_te, y_te = X[teste], y[teste]

    print(f"\n--- teste em {ano} "
          f"(treino {int(anos[treino].min())}–{ano - 2}: {len(X_tr):,} linhas | "
          f"validação {ano - 1}: {len(X_val):,} | teste: {len(X_te):,}) ---")

    resultado = {
        "ano": ano,
        "linhas_treino": int(len(X_tr)),
        "linhas_teste": int(len(X_te)),
        "variantes": {},
        "limiares": {},
    }

    for nome, construtor in (
        ("floresta", lambda: construir_modelo(ARVORES, PROFUNDIDADE, SEMENTE, FOLHA)),
        ("boosting", lambda: estudo.construir_boosting(SEMENTE)),
    ):
        relogio = time.perf_counter()
        modelo = construtor()
        modelo.fit(X_tr, y_tr)

        # Limiar escolhido na validação (ano Y-1), nunca no teste.
        limiar, _ = estudo.escolher_limiar(modelo, X_val, y_val)

        probabilidades = modelo.predict_proba(X_te)
        classes = list(modelo.classes_)
        i_alto = classes.index("alto")

        # Decisão padrão: a classe de maior probabilidade.
        por_argmax = np.array(classes)[probabilidades.argmax(axis=1)]
        # Decisão com limiar: "alto" assim que a probabilidade passa do corte.
        por_limiar = estudo._aplicar_limiar(probabilidades, classes, i_alto, limiar)

        resultado["variantes"][nome] = estudo.medir(y_te, por_argmax)
        resultado["variantes"][f"{nome}+limiar"] = estudo.medir(y_te, por_limiar)
        resultado["limiares"][nome] = round(limiar, 3)

        segundos = time.perf_counter() - relogio
        estudo.linha(nome, resultado["variantes"][nome], f"{segundos:5.0f}s")
        estudo.linha(f"{nome} + limiar {limiar:.2f}",
                     resultado["variantes"][f"{nome}+limiar"])

    return resultado


def comparar(por_ano: list[dict], referencia: str, candidato: str) -> dict:
    """
    Diferença ano a ano entre duas variantes, na acurácia balanceada.

    Além da média, roda um **teste t pareado**. Pareado porque cada ano é
    testado pelos dois modelos nas mesmas linhas: o que interessa não é se um
    modelo tem média maior (a variação entre anos é enorme, ±5 pontos), e sim
    se a DIFERENÇA entre eles é consistentemente positiva. Comparar as médias
    soltas esconderia o sinal dentro do ruído dos anos.

    Seis anos são poucos para um teste t confortável, então o p-valor entra
    como indicação, não como veredito — quem decide é o critério de vitórias
    fixado antes da medição.
    """
    diferencas = np.array([
        r["variantes"][candidato]["balanceada"] - r["variantes"][referencia]["balanceada"]
        for r in por_ano
    ])
    vitorias = int((diferencas > 0).sum())

    teste = {}
    if len(diferencas) > 1 and diferencas.std() > 0:
        from scipy import stats

        t, p_bilateral = stats.ttest_rel(
            [r["variantes"][candidato]["balanceada"] for r in por_ano],
            [r["variantes"][referencia]["balanceada"] for r in por_ano],
        )
        teste = {
            "t": float(t),
            "graus_de_liberdade": len(diferencas) - 1,
            "p_bilateral": float(p_bilateral),
            # A hipótese aqui tem direção: a pergunta é se o candidato é
            # MELHOR, não se é diferente. Daí a versão unilateral.
            "p_unilateral": float(p_bilateral / 2 if t > 0 else 1 - p_bilateral / 2),
        }

    return {
        "referencia": referencia,
        "candidato": candidato,
        "diferenca_por_ano": [round(float(d), 4) for d in diferencas],
        "diferenca_media": float(diferencas.mean()),
        "diferenca_desvio": float(diferencas.std(ddof=1)),
        "vitorias": vitorias,
        "anos": len(diferencas),
        "teste_t_pareado": teste,
        "aprovado": bool(vitorias >= MINIMO_DE_VITORIAS and diferencas.mean() > 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anos", type=int, nargs="+", default=ANOS_PADRAO,
                        help="anos de teste (padrão: 2019 a 2024)")
    parser.add_argument("--dados", type=Path, default=ARQUIVO_DADOS)
    argumentos = parser.parse_args()

    titulo("O GANHO DE +0,7% SE REPETE EM OUTROS ANOS?")
    print("Seis testes independentes, um por ano. O limiar é sempre escolhido")
    print("no ano anterior ao teste — o teste nunca participa de decisão.\n")
    print(f"Regra fixada antes de medir: aprova se vencer em ao menos "
          f"{MINIMO_DE_VITORIAS} dos {len(argumentos.anos)} anos\n"
          f"e a média da diferença for positiva.")

    dados = carregar_dados(argumentos.dados)
    X, y = caracteristicas.separar_x_y(dados)

    print(f"\n{'variante':<40}{'balanceada':>11}{'F1 macro':>11}"
          f"{'risco alto':>12}")

    por_ano = [avaliar_ano(dados, X, y, ano) for ano in argumentos.anos]

    # ---------------------------------------------------------------- resumo
    titulo("MÉDIA DOS ANOS")
    nomes = list(por_ano[0]["variantes"])
    print(f"{'variante':<40}{'balanceada':>11}{'desvio':>9}"
          f"{'F1 macro':>11}{'risco alto':>12}")
    print("-" * 83)
    medias = {}
    for nome in nomes:
        valores = np.array([r["variantes"][nome]["balanceada"] for r in por_ano])
        f1 = np.mean([r["variantes"][nome]["f1_macro"] for r in por_ano])
        alto = np.mean([r["variantes"][nome]["recall_alto"] for r in por_ano])
        medias[nome] = {
            "balanceada_media": float(valores.mean()),
            "balanceada_desvio": float(valores.std()),
            "f1_macro_media": float(f1),
            "recall_alto_media": float(alto),
        }
        print(f"  {nome:<38}{valores.mean():>10.1%}{valores.std():>9.1%}"
              f"{f1:>11.3f}{alto:>12.1%}")

    titulo("ANO A ANO — DIFERENÇA CONTRA A FLORESTA ATUAL")
    comparacoes = {
        nome: comparar(por_ano, "floresta", nome)
        for nome in nomes if nome != "floresta"
    }

    cabecalho = "  ano" + "".join(f"{r['ano']:>10}" for r in por_ano)
    print(cabecalho)
    print("-" * len(cabecalho))
    print("  floresta (base)" + "".join(
        f"{r['variantes']['floresta']['balanceada']:>10.1%}" for r in por_ano))
    for nome, c in comparacoes.items():
        marcas = "".join(
            f"{d:>+10.1%}" for d in c["diferenca_por_ano"]
        )
        print(f"  {nome:<15}" + marcas)

    titulo("VEREDITO")
    for nome, c in comparacoes.items():
        sinal = "APROVADO" if c["aprovado"] else "reprovado"
        print(f"  {nome:<22} média {c['diferenca_media']:>+7.2%}  "
              f"venceu em {c['vitorias']}/{c['anos']} anos  ->  {sinal}")
        if c["teste_t_pareado"]:
            t = c["teste_t_pareado"]
            print(f"  {'':22} teste t pareado: t={t['t']:+.2f}, "
                  f"gl={t['graus_de_liberdade']}, "
                  f"p={t['p_unilateral']:.3f} (unilateral)")

    print()
    aprovadas = [n for n, c in comparacoes.items() if c["aprovado"]]
    if aprovadas:
        melhor = max(aprovadas, key=lambda n: comparacoes[n]["diferenca_media"])
        print(f"  Mudança a aplicar no projeto: {melhor} "
              f"({comparacoes[melhor]['diferenca_media']:+.2%} em média).")
    else:
        print("  Nenhuma variante passou no critério. O modelo atual fica.")

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "validacao_ganho.json"
    saida.write_text(json.dumps({
        "protocolo": {
            "anos_testados": argumentos.anos,
            "treino": "tudo até o ano Y-2",
            "validacao": "ano Y-1 (escolha do limiar)",
            "teste": "ano Y",
            "minimo_de_vitorias": MINIMO_DE_VITORIAS,
            "modelo_floresta": {"arvores": ARVORES, "profundidade": PROFUNDIDADE,
                                "folha": FOLHA},
        },
        "por_ano": por_ano,
        "medias": medias,
        "comparacoes": comparacoes,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
