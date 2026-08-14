# Pasta de dados

O treinamento espera um arquivo `dados/dados.csv` no formato definido em
[`src/esquema.py`](../src/esquema.py). Esse arquivo é **gerado** a partir da
base bruta do Atlas de Desastres:

```
dados/
├── bruto/            base bruta baixada do Atlas (não vai para o Git)
├── dados.csv         dataset de treino (gerado)
├── ocorrencias.csv   ocorrências limpas, usadas pela API nas consultas (gerado)
└── procedencia.json  registro da origem do dataset (gerado)
```

Nenhum CSV desta pasta vai para o Git: a base bruta tem 82 MB e os arquivos
derivados são reproduzíveis por script.

## Como gerar o dataset

1. Baixe a base consolidada no **Atlas Digital de Desastres no Brasil**:
   <https://atlasdigital.mi.gov.br> — o arquivo tem nome parecido com
   `BD_Atlas_1991_2025_v1.1_..._Consolidado.csv`.
2. Salve em `dados/bruto/`.
3. Rode, a partir da raiz do projeto:

```bash
python dados/preparar_dados.py
```

O script encontra o arquivo sozinho, limpa, monta o dataset e registra a
procedência como **real**.

## O que a base bruta traz (e o que não traz)

O Atlas é um registro de **ocorrências**: cada linha é um desastre que
aconteceu, com município, data, tipologia COBRADE, danos humanos e prejuízos
declarados. São 76 mil registros entre 1991 e 2025, em 5.256 municípios.

O que ele **não** traz: chuva, temperatura, umidade, declividade, vegetação.
Ou seja, o Atlas diz *o que aconteceu*, mas não traz o *gatilho climático*.
Por isso as variáveis do modelo são de histórico, sazonalidade e geografia.
Quando as séries do INMET/CEMADEN forem incorporadas, elas entram como
colunas novas em `src/esquema.py` e no ETL — o resto do projeto não muda.

### Detalhes do arquivo bruto

Coisas que quebram a leitura se ignoradas, e que o ETL já trata:

| Característica | Valor |
| --- | --- |
| Separador | ponto e vírgula (`;`) |
| Decimal | vírgula (`,`) |
| Codificação | **cp850** (não é UTF-8 nem latin-1) |
| Data | `DD/MM/AAAA` |

## Como o dataset de treino é construído

Uma linha = **um município, em um mês, para um tipo de desastre**.

| codigo_ibge | municipio  | ano  | mes | grupo_desastre | ... | nivel_risco |
| ----------- | ---------- | ---- | --- | -------------- | --- | ----------- |
| 3303906     | Petrópolis | 2024 | 2   | DESLIZAMENTO   | ... | alto        |
| 3303906     | Petrópolis | 2024 | 2   | INUNDACAO      | ... | medio       |
| 3303906     | Petrópolis | 2024 | 3   | DESLIZAMENTO   | ... | baixo       |

Para ver a lista completa de colunas, com unidade e faixa de cada uma:

```bash
python -m src.esquema
```

### 1. Os exemplos negativos

O Atlas só registra o que **aconteceu**. Um modelo treinado só com desastres
aprenderia que tudo é desastre. O ETL então gera as linhas de meses em que
**nada** ocorreu — são elas que definem o nível `baixo`.

Por padrão são amostrados 3 meses sem ocorrência para cada mês com ocorrência.
A proporção real de meses tranquilos é muito maior; a amostragem existe para o
arquivo caber no treino.

> **Consequência a declarar na apresentação:** as probabilidades do modelo
> medem risco **relativo** entre municípios, não a chance absoluta de um
> desastre acontecer naquele mês.

### 2. O rótulo `nivel_risco`

O S2iD registra **o que aconteceu**, não "o nível de risco". O rótulo é
construído a partir dos registros, e essa decisão é metodológica — vale
descrevê-la na apresentação, porque é o coração do trabalho.

| nivel_risco | critério |
| ----------- | --------------------------------------------------------- |
| `baixo`     | nenhuma ocorrência registrada no município, no mês, para o tipo |
| `medio`     | ocorrência registrada, sem reconhecimento federal e sem mortos |
| `alto`      | ocorrência com mortos, ou com reconhecimento de emergência/calamidade |

A coluna `Status` do Atlas distingue `Registro` de `Reconhecido` — é ela que
separa `medio` de `alto`, junto com `DH_MORTOS`.

### 3. As features, sem vazamento temporal

Todas as variáveis de um mês são calculadas **apenas** com ocorrências
anteriores a ele. O corte usa busca binária com `side="left"`, o que exclui o
próprio mês.

Isso é o ponto mais delicado do projeto: se o histórico de fevereiro incluísse
o que aconteceu em fevereiro, o modelo "preveria" o passado e a acurácia sairia
alta e inútil. O teste
[`test_historico_nao_usa_o_proprio_mes_nem_o_futuro`](../testes/test_dados.py)
confere isso linha a linha.

Pelo mesmo motivo, o treinamento usa **divisão temporal** (treina até 2021,
testa de 2022 em diante) em vez de divisão aleatória. É assim que o sistema
seria usado de verdade.

### 4. Tipologias aproveitadas

Dez grupos, cobrindo 97,6% dos registros:

`ESTIAGEM_SECA`, `INUNDACAO`, `ENXURRADA`, `ALAGAMENTO`, `CHUVAS_INTENSAS`,
`DESLIZAMENTO`, `VENDAVAL_CICLONE`, `GRANIZO`, `INCENDIO_FLORESTAL`, `EROSAO`.

Descartadas: `Outros` (sem definição própria), `Doenças infecciosas` (não é
desastre climático/geofísico), `Onda de Frio`, `Onda de Calor` e
`Rompimento/Colapso de barragens` (poucos registros e sem variável explicativa
no que o Atlas oferece hoje).

## Limitações conhecidas

Vale ter estas respostas prontas para a banca:

- **Subnotificação.** Município que não registra ocorrência aparece como sem
  risco. O número de registros cresce ao longo dos anos, o que reflete tanto
  mais eventos quanto mais notificação.
- **Sem gatilho climático.** O modelo sabe que Petrópolis é perigosa em
  fevereiro, mas não sabe se vai chover neste fevereiro.
- **Só municípios com histórico.** Quem nunca registrou nada não está na base;
  o sistema não opina sobre eles.
- **O rótulo é uma construção nossa**, derivada dos danos declarados, e não
  uma medida oficial de risco.

## Dados climáticos do INMET (em construção)

O Atlas diz *o que aconteceu*, mas não traz o gatilho: a chuva. A leitura dos
dados do INMET já está pronta e testada — falta baixar os arquivos e juntar ao
dataset de treino.

### Como baixar

**1. Dados das estações** — <https://portal.inmet.gov.br/dadoshistoricos>

Um ZIP por ano, de 2000 a 2026. Baixe os anos desejados e descompacte
**todos** dentro de `dados/bruto/inmet/`. Podem ficar em subpastas por ano; a
busca é recursiva.

> Cada ZIP tem de 40 a 120 MB. Para só testar o encanamento, comece com dois
> ou três anos recentes. Para o projeto completo, o ideal é 2000–2025: os anos
> 2000–2009 servem de **normal climatológica** e os demais alimentam o modelo.

**2. Lista de municípios do IBGE** — baixada automaticamente pelo script, ou:

```bash
curl -o dados/bruto/municipios_ibge.json \
  https://servicodados.ibge.gov.br/api/v1/localidades/municipios
```

### Como processar

```bash
python dados/preparar_clima.py
```

Gera `dados/clima_mensal.csv` (chuva por município e mês) e
`dados/clima_normais.csv` (a chuva típica de cada estação em cada mês).

### Como a chuva chega a cada município

O INMET tem ~600 estações automáticas; o Brasil tem 5.571 municípios. Cada
município recebe a medição do nível mais próximo disponível:

| Nível | O que significa |
| --- | --- |
| `municipio` | há uma estação no próprio município |
| `regiao_imediata` | estação na mesma região imediata do IBGE (~510 no país) |
| `regiao_intermediaria` | estação na mesma região intermediária (~133) |
| `uf` | média das estações do estado |

O nível usado fica gravado na coluna `fonte_clima` de cada linha. Isso importa
na hora de analisar: chuva medida no próprio município e chuva estimada pela
média do estado têm qualidade muito diferente.

As estações são casadas aos municípios por **nome normalizado + UF**. A UF
entra na chave porque há dezenas de nomes repetidos no Brasil — existem duas
"Santa Maria" em estados diferentes, e casar só pelo nome jogaria a chuva de um
estado no outro.

### Detalhes do formato

O leitor trata sozinho as armadilhas do arquivo:

| Característica | Valor |
| --- | --- |
| Cabeçalho | 8 linhas de metadados antes dos dados |
| Separador | ponto e vírgula (`;`) |
| Decimal | vírgula (`,`) |
| Codificação | latin-1 (com UTF-8 tentado antes, porque latin-1 nunca falha) |
| Faltante | `-9999` |
| Frequência | horária |

**Os nomes das colunas mudam entre os anos.** O INMET alterou grafias,
acentuação e o formato da data ao longo do tempo, então as colunas são
procuradas por palavra-chave, nunca pelo nome exato. Mês com menos de 50% das
horas registradas é descartado: estação meio fora do ar produziria uma "chuva
mensal" falsamente baixa.

### O que ainda falta

Juntar o clima ao dataset de treino, respeitando a regra de não usar o futuro:
as variáveis de um mês precisam vir dos meses **anteriores** (chuva do mês
passado, acumulado de três meses, anomalia em relação à normal). Isso mede o
mecanismo real — solo encharcado do mês anterior aumenta o risco de
deslizamento — sem exigir saber a chuva do mês que se quer prever.

## Outras fontes, para os próximos passos

- **INMET (BDMEP)**: <https://bdmep.inmet.gov.br> — chuva, temperatura, umidade
  e vento por estação. As normais climatológicas (1991–2020) permitem calcular
  anomalia de chuva.
- **CEMADEN**: <https://www.cemaden.gov.br/mapainterativo/> — pluviômetros
  automáticos e umidade do solo.
- **IBGE**: área, população, densidade e a malha municipal (que traz também as
  coordenadas necessárias para o mapa).
- **TOPODATA/INPE** ou **CPRM**: altitude e declividade.
- **MapBiomas**: <https://mapbiomas.org> — cobertura vegetal.

Todas se ligam ao Atlas pelo **código IBGE do município**.
