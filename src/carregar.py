"""
Carregamento e validação do dataset.

A validação roda ANTES do treino. Ela existe para que um problema na base
apareça como uma mensagem clara ("faltou a coluna X", "a coluna Y tem 300
valores negativos") em vez de virar um modelo treinado em cima de lixo, ou um
erro incompreensível do sklearn lá na frente.
"""

from pathlib import Path

import pandas as pd

from src import esquema


class ErroDeDados(Exception):
    """Problema na base que impede o treinamento de continuar."""


class Relatorio:
    """Resultado da validação: erros travam o treino, avisos apenas informam."""

    def __init__(self) -> None:
        self.erros: list[str] = []
        self.avisos: list[str] = []

    @property
    def valido(self) -> bool:
        return not self.erros

    def imprimir(self) -> None:
        for aviso in self.avisos:
            print(f"  [aviso] {aviso}")
        for erro in self.erros:
            print(f"  [ERRO]  {erro}")
        if not self.avisos and not self.erros:
            print("  Nenhum problema encontrado.")


def validar(dados: pd.DataFrame, exigir_alvo: bool = True) -> Relatorio:
    """Confere se o DataFrame respeita o contrato definido em `esquema.py`."""
    rel = Relatorio()

    # --- 1. Colunas obrigatórias -------------------------------------------
    esperadas = list(esquema.COLUNAS_OBRIGATORIAS)
    if not exigir_alvo:
        esperadas = [c for c in esperadas if c != esquema.COLUNA_ALVO]

    faltando = [c for c in esperadas if c not in dados.columns]
    if faltando:
        rel.erros.append(
            f"Faltam {len(faltando)} coluna(s) obrigatória(s): {', '.join(faltando)}"
        )
        # Sem as colunas não dá para validar o resto.
        return rel

    extras = [c for c in dados.columns if c not in esperadas
              and c != esquema.COLUNA_ALVO]
    if extras:
        rel.avisos.append(
            f"{len(extras)} coluna(s) do CSV serão ignoradas pelo modelo: "
            f"{', '.join(extras[:10])}"
        )

    if len(dados) == 0:
        rel.erros.append("O arquivo não tem nenhuma linha de dados.")
        return rel

    # --- 2. Tipos numéricos -------------------------------------------------
    for coluna in esquema.COLUNAS_NUMERICAS + ["ano", "mes", "codigo_ibge"]:
        if not pd.api.types.is_numeric_dtype(dados[coluna]):
            convertida = pd.to_numeric(dados[coluna], errors="coerce")
            nao_convertidos = convertida.isna().sum() - dados[coluna].isna().sum()
            if nao_convertidos > 0:
                rel.erros.append(
                    f"'{coluna}' deveria ser numérica, mas tem {nao_convertidos} "
                    f"valor(es) que não são número (texto, símbolo, vírgula decimal?)"
                )

    # --- 3. Valores fora da faixa esperada ----------------------------------
    for coluna in esquema.COLUNAS_NUMERICAS + ["ano", "mes"]:
        info = esquema.POR_NOME[coluna]
        serie = pd.to_numeric(dados[coluna], errors="coerce")

        if info.minimo is not None:
            abaixo = int((serie < info.minimo).sum())
            if abaixo:
                rel.avisos.append(
                    f"'{coluna}': {abaixo} valor(es) abaixo do mínimo esperado "
                    f"({info.minimo} {info.unidade})".strip()
                )
        if info.maximo is not None:
            acima = int((serie > info.maximo).sum())
            if acima:
                rel.avisos.append(
                    f"'{coluna}': {acima} valor(es) acima do máximo esperado "
                    f"({info.maximo} {info.unidade})".strip()
                )

    # --- 4. Valores faltantes ------------------------------------------------
    for coluna in esquema.COLUNAS_NUMERICAS + esquema.COLUNAS_CATEGORICAS:
        info = esquema.POR_NOME[coluna]
        nulos = int(dados[coluna].isna().sum())
        if nulos == 0:
            continue

        proporcao = nulos / len(dados)
        if not info.permite_nulo and proporcao > 0.30:
            rel.avisos.append(
                f"'{coluna}': {proporcao:.0%} dos valores estão vazios. "
                f"Serão preenchidos automaticamente, mas com essa proporção a "
                f"coluna contribui pouco — considere revisar a coleta."
            )
        elif not info.permite_nulo:
            rel.avisos.append(
                f"'{coluna}': {nulos} valor(es) vazio(s), serão preenchidos "
                f"automaticamente."
            )

    # --- 5. Categorias fora do domínio ---------------------------------------
    for coluna in esquema.COLUNAS_CATEGORICAS:
        info = esquema.POR_NOME[coluna]
        if not info.categorias:
            continue
        presentes = set(dados[coluna].dropna().unique())
        desconhecidas = presentes - set(info.categorias)
        if desconhecidas:
            rel.avisos.append(
                f"'{coluna}': valor(es) fora da lista conhecida: "
                f"{', '.join(sorted(map(str, desconhecidas))[:8])}. "
                f"Confira a grafia ou acrescente em src/esquema.py."
            )

    # --- 6. Linhas duplicadas -------------------------------------------------
    chave = esquema.CHAVE_LINHA
    duplicadas = int(dados.duplicated(subset=chave).sum())
    if duplicadas:
        rel.avisos.append(
            f"{duplicadas} linha(s) repetem a combinação "
            f"município + ano + mês + tipo de desastre. Linhas repetidas fazem o "
            f"modelo dar peso extra a esses casos."
        )

    # --- 7. O alvo ------------------------------------------------------------
    if exigir_alvo:
        alvo = dados[esquema.COLUNA_ALVO]

        nulos_alvo = int(alvo.isna().sum())
        if nulos_alvo:
            rel.erros.append(
                f"'{esquema.COLUNA_ALVO}': {nulos_alvo} linha(s) sem rótulo. "
                f"Remova essas linhas ou preencha o nível de risco."
            )

        invalidos = set(alvo.dropna().unique()) - set(esquema.CLASSES_RISCO)
        if invalidos:
            rel.erros.append(
                f"'{esquema.COLUNA_ALVO}' só aceita "
                f"{esquema.CLASSES_RISCO}, mas encontrei: "
                f"{sorted(map(str, invalidos))}"
            )

        contagem = alvo.value_counts()
        ausentes = [c for c in esquema.CLASSES_RISCO if c not in contagem.index]
        if ausentes:
            rel.erros.append(
                f"Nenhum exemplo das classes {ausentes}. O modelo não consegue "
                f"aprender a prever um nível que nunca viu."
            )

        for classe, n in contagem.items():
            if n < 10:
                rel.avisos.append(
                    f"A classe '{classe}' tem só {n} exemplo(s). "
                    f"As métricas para ela não serão confiáveis."
                )

        if len(contagem) > 1:
            desbalanceamento = contagem.max() / contagem.min()
            if desbalanceamento > 20:
                rel.avisos.append(
                    f"Classes bem desbalanceadas ({desbalanceamento:.0f}x entre a "
                    f"mais e a menos comum). O treino usa class_weight='balanced' "
                    f"para compensar, mas vale olhar o recall da classe 'alto'."
                )

    return rel


def carregar_dados(
    caminho: Path,
    validar_dados: bool = True,
    exigir_alvo: bool = True,
) -> pd.DataFrame:
    """Lê o CSV, valida e devolve o DataFrame pronto para o treino."""
    if not caminho.exists():
        raise ErroDeDados(
            f"Arquivo não encontrado: {caminho}\n\n"
            f"A base de dados real ainda não foi colocada no projeto.\n"
            f"Para testar o pipeline enquanto isso, gere dados de exemplo:\n\n"
            f"    python dados/gerar_dados_sinteticos.py\n"
        )

    dados = pd.read_csv(caminho)
    print(f"Lidas {len(dados):,} linhas e {len(dados.columns)} colunas de {caminho.name}")

    if not validar_dados:
        return dados

    print("\nValidando os dados...")
    relatorio = validar(dados, exigir_alvo=exigir_alvo)
    relatorio.imprimir()

    if not relatorio.valido:
        raise ErroDeDados(
            f"\n{len(relatorio.erros)} problema(s) impedem o treinamento. "
            f"Corrija o CSV e rode de novo."
        )

    return dados


def resumir(dados: pd.DataFrame) -> None:
    """Imprime um panorama rápido da base. Útil quando a base real chegar."""
    print(f"\nPeríodo coberto: {dados['ano'].min()} a {dados['ano'].max()}")
    print(f"Municípios distintos: {dados['codigo_ibge'].nunique():,}")
    print(f"UFs distintas: {dados['uf'].nunique()}")

    print("\nLinhas por grupo de desastre:")
    for grupo, n in dados["grupo_desastre"].value_counts().items():
        print(f"  {grupo:<20} {n:>8,}")

    if esquema.COLUNA_ALVO in dados.columns:
        print("\nDistribuição do nível de risco:")
        contagem = dados[esquema.COLUNA_ALVO].value_counts()
        for classe in esquema.CLASSES_RISCO:
            n = int(contagem.get(classe, 0))
            print(f"  {classe:<20} {n:>8,}  ({n / len(dados):.1%})")
