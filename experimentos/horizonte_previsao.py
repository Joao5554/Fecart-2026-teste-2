"""
Até onde no futuro a previsão ainda significa alguma coisa?

A interface vai passar a oferecer os meses de setembro/2026 a dezembro/2027.
Isso levanta uma pergunta que nenhuma métrica de acurácia responde: o modelo
foi treinado com dados que terminam em 2025 — o que acontece com as variáveis
quando se pede um mês cada vez mais distante desse fim?

Quatro das variáveis mais importantes são contagens de janela móvel:

    ocorrencias_12m              ocorrências do tipo no município (12 meses)
    ocorrencias_municipio_12m    ocorrências de qualquer tipo (12 meses)
    ocorrencias_uf_grupo_12m     ocorrências do tipo na UF (12 meses)
    meses_desde_ultima_ocorrencia

As três primeiras olham para trás 12 meses a partir do mês pedido. Se o mês
pedido está a mais de 12 meses do último registro, essa janela cai inteira num
período sem dado nenhum, e as três viram ZERO — não porque nada aconteceu, mas
porque o Atlas ainda não chegou lá. A quarta cresce sem parar.

A correção está em `src/atlas._ancora`: as janelas param no fim da base, em
vez de varrerem um vazio. Este script mede os dois comportamentos lado a lado
— o corrigido e o antigo — para mostrar o tamanho do estrago que existia.

Como rodar (a partir da raiz do projeto):
    python experimentos/horizonte_previsao.py
"""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import atlas, caracteristicas, esquema  # noqa: E402

ARQUIVO_OCORRENCIAS = RAIZ / "dados" / "ocorrencias.csv"
ARQUIVO_MODELO = RAIZ / "modelo" / "modelo.pkl"
PASTA_SAIDA = Path(__file__).resolve().parent / "resultados"

# A janela que a interface vai oferecer.
PRIMEIRO = (2026, 9)
ULTIMO = (2027, 12)

# Variáveis que dependem de uma janela móvel — as que envelhecem.
DE_JANELA = [
    "ocorrencias_12m",
    "ocorrencias_24m",
    "ocorrencias_60m",
    "ocorrencias_municipio_12m",
    "ocorrencias_uf_grupo_12m",
    "meses_desde_ultima_ocorrencia",
]


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def meses_da_janela() -> list[tuple[int, int]]:
    """Todos os (ano, mês) de PRIMEIRO até ULTIMO, inclusive."""
    inicio = int(atlas._indice_mes(*PRIMEIRO))
    fim = int(atlas._indice_mes(*ULTIMO))
    return [(1900 + i // 12, i % 12 + 1) for i in range(inicio, fim + 1)]


def medir(historico, pares, municipios, modelo, classes, i_alto,
          ultimo_indice) -> pd.DataFrame:
    """Roda o modelo em cada mês da janela e resume o que ele respondeu."""
    linhas = []
    for ano, mes in meses_da_janela():
        alvos = pares.assign(indice_mes=atlas._indice_mes(ano, mes))
        entrada = atlas.calcular_features(historico, alvos)
        entrada["prejuizo_historico_log"] = np.log1p(entrada["prejuizo_historico"])
        entrada["mes"] = mes
        entrada = entrada.merge(municipios, on="codigo_ibge", how="left")

        X = caracteristicas.preparar_para_previsao(entrada)
        probabilidades = modelo.predict_proba(X)
        previsto = np.array(classes)[probabilidades.argmax(axis=1)]

        registro = {
            "ano": ano,
            "mes": mes,
            "distancia_meses": int(atlas._indice_mes(ano, mes)) - ultimo_indice,
            "p_alto_media": float(probabilidades[:, i_alto].mean()),
            "fatia_alto": float((previsto == "alto").mean()),
            "fatia_baixo": float((previsto == "baixo").mean()),
        }
        for coluna in DE_JANELA:
            registro[coluna] = float(entrada[coluna].mean())
        linhas.append(registro)

    return pd.DataFrame(linhas)


def main() -> int:
    titulo("ATÉ ONDE A PREVISÃO AINDA SIGNIFICA ALGUMA COISA?")

    # Mesmo arquivo que a API lê em execução — e pelo mesmo caminho.
    ocorrencias = pd.read_csv(ARQUIVO_OCORRENCIAS)
    historico = atlas.agregar_por_mes(ocorrencias)

    ultimo_indice = int(historico["indice_mes"].max())
    # `_indice_mes` conta meses desde janeiro de 1900; desfazer a conta devolve
    # o mês de calendário.
    ultimo_ano, ultimo_mes = 1900 + ultimo_indice // 12, ultimo_indice % 12 + 1
    print(f"Último mês com registro no Atlas: {ultimo_mes:02d}/{ultimo_ano}")

    modelo = joblib.load(ARQUIVO_MODELO)
    classes = list(modelo.classes_)
    i_alto = classes.index("alto")

    # Todos os pares (município, tipo) com histórico entram: a pergunta é sobre
    # o comportamento médio do sistema, não sobre uma cidade específica.
    pares = historico[["codigo_ibge", "grupo_desastre"]].drop_duplicates()
    print(f"Pares (município, tipo) avaliados: {len(pares):,}")

    municipios = (
        ocorrencias.sort_values("ano")
        .groupby("codigo_ibge")[["uf", "regiao"]].last()
    )

    argumentos = (historico, pares, municipios, modelo, classes, i_alto,
                  ultimo_indice)

    com_ancora = medir(*argumentos)

    # O comportamento antigo, para comparação: desliga a âncora e refaz tudo.
    # É a única forma honesta de dizer o tamanho do problema — sem o "antes",
    # a tabela do "depois" não prova nada.
    original = atlas._ancora
    atlas._ancora = lambda historico, meses: meses
    try:
        sem_ancora = medir(*argumentos)
    finally:
        atlas._ancora = original

    titulo("O QUE O MODELO RESPONDE, MÊS A MÊS")
    print("'antes' = janelas varrendo o vazio depois do fim da base;")
    print("'depois' = janelas paradas no último mês com dado.\n")
    print(f"{'mês':>9}{'meses além':>12}"
          f"{'% alto ANTES':>15}{'% alto DEPOIS':>16}{'diferença':>12}")
    print("-" * 64)
    for (_, antes), (_, depois) in zip(sem_ancora.iterrows(),
                                       com_ancora.iterrows()):
        diferenca = depois["fatia_alto"] - antes["fatia_alto"]
        print(f"{int(depois['mes']):02d}/{int(depois['ano'])}"
              f"{int(depois['distancia_meses']):>11}"
              f"{antes['fatia_alto']:>14.1%}{depois['fatia_alto']:>16.1%}"
              f"{diferenca:>+12.1%}")

    titulo("AS VARIÁVEIS DE JANELA MÓVEL — ANTES E DEPOIS")
    for nome, tabela in (("ANTES", sem_ancora), ("DEPOIS", com_ancora)):
        print(f"\n{nome}")
        print(f"{'mês':>9}" + "".join(
            f"{c.replace('ocorrencias_', 'oc_')[:13]:>15}" for c in DE_JANELA))
        print("-" * (9 + 15 * len(DE_JANELA)))
        for _, l in tabela.iterrows():
            print(f"{int(l['mes']):02d}/{int(l['ano'])}"
                  + "".join(f"{l[c]:>15.2f}" for c in DE_JANELA))

    titulo("LEITURA")
    primeira, ultima = sem_ancora.iloc[0], sem_ancora.iloc[-1]
    print("ANTES — a previsão derretia com a distância:")
    print(f"  municípios em risco alto: {primeira['fatia_alto']:.1%} "
          f"({int(primeira['mes']):02d}/{int(primeira['ano'])}) -> "
          f"{ultima['fatia_alto']:.1%} "
          f"({int(ultima['mes']):02d}/{int(ultima['ano'])})")
    print(f"  ocorrencias_uf_grupo_12m: {primeira['ocorrencias_uf_grupo_12m']:.1f}"
          f" -> {ultima['ocorrencias_uf_grupo_12m']:.1f}")
    zerados = sem_ancora[sem_ancora["ocorrencias_12m"] < 0.005]
    if not zerados.empty:
        z = zerados.iloc[0]
        print(f"  a partir de {int(z['mes']):02d}/{int(z['ano'])} a janela de 12"
              f" meses não alcançava registro nenhum,")
        print("  e o modelo via 'nada aconteceu no último ano' em TODO o país.")

    print("\nDEPOIS — o que sobra é sazonalidade, que é o que ele sabe:")
    por_mes = com_ancora.groupby("mes")["fatia_alto"].first()
    pico, vale = por_mes.idxmax(), por_mes.idxmin()
    print(f"  mês de maior risco: {pico:02d} ({por_mes[pico]:.1%} dos municípios)")
    print(f"  mês de menor risco: {vale:02d} ({por_mes[vale]:.1%})")

    repetidos = com_ancora.groupby("mes")["fatia_alto"].nunique().max()
    if repetidos == 1:
        print("\n  Consequência honesta: o mesmo mês de 2026 e de 2027 recebe a")
        print("  MESMA resposta. Sem dado novo, não existe nada que distinga um")
        print("  do outro — e fingir que existe seria inventar informação.")

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    saida = PASTA_SAIDA / "horizonte_previsao.json"
    saida.write_text(json.dumps({
        "ultimo_mes_com_dado": f"{ultimo_mes:02d}/{ultimo_ano}",
        "pares_avaliados": int(len(pares)),
        "com_ancora": com_ancora.to_dict(orient="records"),
        "sem_ancora": sem_ancora.to_dict(orient="records"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
