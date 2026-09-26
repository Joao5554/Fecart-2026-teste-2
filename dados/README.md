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

## Vento predominante (camada dos mapas)

`dados/vento_estacoes.csv` — uma linha por estação do INMET e por mês, com o
vento predominante daquele mês. É o que a camada de vento dos mapas desenha.

```
python dados/preparar_vento.py
```

O script baixa sozinho os ZIPs anuais do INMET que faltarem (padrão: 2021 a
2025, ~470 MB, em `dados/bruto/inmet/`), lê a direção e a velocidade horárias
de cada estação e reduz tudo a 12 linhas por estação. O CSV final tem 0,6 MB e
vai versionado, como o de chuva: reconstruí-lo exige o download inteiro.

### É climatologia, não previsão de curto prazo

A resposta de "março" é o **março típico**, apurado sobre todos os anos
baixados — e não o março de um ano específico, nem os próximos dias.

Isso é deliberado, e é o que casa com o resto do projeto: a previsão de risco
também é por mês. Perguntar "risco de vendaval em Petrópolis em fevereiro" e
receber o vento que fevereiro costuma trazer é a mesma pergunta, respondida
pelos dois lados.

Um campo como o do Windy — as próximas horas, atualizado o dia todo — sai de
um modelo global (GFS, do NOAA, ou ECMWF) rodado quatro vezes por dia. Exigiria
internet a cada abertura da página, o que o projeto inteiro evita de propósito.

### Por que a média é vetorial

Direção é ângulo, e ângulo não se soma. A média aritmética de 350° e 10° dá
**180°** — o rumo exatamente oposto ao de duas medições que quase coincidem.

Cada hora vira um vetor antes de qualquer média:

```
u = -velocidade * sen(direção)     (componente para leste)
v = -velocidade * cos(direção)     (componente para norte)
```

O sinal negativo está aí porque a direção meteorológica diz de onde o vento
**vem**, e o vetor aponta para onde ele **vai**: vento de norte (0°) sopra
para o sul. Somadas as componentes, 350° e 10° dão 0°, que é a resposta certa.

A conta está em `src/inmet.py`, na `agregar_mensal`, e o caminho de volta
(`direcao_do_vetor`) em `dados/preparar_vento.py`. Os testes em
`testes/test_clima_vento.py` protegem exatamente esse ponto — é um erro que
não quebra nada, não levanta exceção e só desenha o mapa ao contrário.

### A coluna `constancia`

Vai de 0 a 1: é o módulo do vetor médio dividido pela velocidade média.

Perto de **1**, o vento soprou sempre para o mesmo lado, e a direção
predominante significa o que parece — é o caso dos alísios do Nordeste, que
passam de 0,90 em Fortaleza e Natal. Perto de **0**, a direção variou tanto
que a predominante é quase um empate: o Sul em julho fica abaixo de 0,10,
porque o vento ali gira a cada frente que passa.

Sem esse número, um alísio firme e um mês de vento caótico desenhariam
exatamente a mesma seta.

## Temperatura (a camada de mapa de calor)

`dados/temperatura_estacoes.csv` — uma linha por estação do INMET, por ano e
por mês, com a temperatura média, a máxima e a mínima daquele mês.

```
python dados/preparar_temperatura.py
```

O script baixa os mesmos ZIPs anuais que a camada de vento usa (padrão: 2021 a
2025) — se o vento já foi preparado, não baixa nada de novo — e lê a coluna de
temperatura horária de cada estação. O CSV final tem 1,8 MB, com 603 estações,
e vai versionado.

### Por que ano E mês, diferente do vento

O vento guarda só doze linhas por estação, porque direção não tem sentido fora
de um mês. Temperatura é média, e média de médias continua sendo média — então
guardar ano e mês deixa o mesmo arquivo responder às três perguntas dos mapas:

| Pedido | Resposta |
| --- | --- |
| `mes`, sem `ano` | O mês **típico**, apurado sobre todos os anos baixados |
| `ano`, sem `mes` | A média daquele ano |
| `ano` e `mes` | Aquele mês daquele ano |

### Máxima e mínima são médias, não picos

A "máxima" de um mês é a **média das máximas diárias**, não o pico absoluto. É
a definição climatológica, e é a única robusta: o pico absoluto é um único
registro, e um sensor com uma leitura maluca viraria "a máxima do mês". A média
de trinta máximas diárias absorve o erro de uma delas.

### A ordem das três etapas do preparo

1. Descartar sensor com defeito, linha a linha (fora de −25 a 55 °C).
2. Agrupar, com média **ponderada pelas horas medidas**.
3. Só então cortar o mês mal medido (menos de 240 horas).

Cortar antes de agrupar é o erro sutil: o mesmo mês da mesma estação aparece
em duas linhas sempre que o ano foi baixado solto **e** dentro de um ZIP, e
duas metades de 150 horas seriam jogadas fora separadamente — quando juntas
fazem um mês de 300 horas, bem medido. O teste
[`test_a_media_de_linhas_repetidas_e_ponderada_pelas_horas`](../testes/test_clima_temperatura.py)
protege esse ponto.

### O que a camada não corrige: a altitude

O ar esfria cerca de **6,5 °C a cada 1.000 m**, e a interpolação entre
estações não sabe onde estão as serras. Perto de cada estação o número é o
medido; entre duas, o desenho trata o relevo como uma rampa.

É a limitação principal desta camada, e ela está dita no rodapé da própria
camada, na tela.

**A grade de altitude que a correção pede já existe**: é a
`dados/relevo_brasil.bin`, descrita no fim deste arquivo, criada para a camada
de relevo. Com ela, a conta certa é reduzir cada estação ao nível do mar
(somando 6,5 °C por 1.000 m de altitude da estação), interpolar esse campo — que
é liso, e governado por latitude e continentalidade — e devolver o lapso usando
a altitude real de cada ponto do desenho. É a correção clássica, e agora é um
trabalho pequeno: o que faltava era o dado, não o método.

Ainda não foi feita porque muda o número que a camada mostra, e trocar uma
medição por uma estimativa corrigida pede uma rodada de conferência contra as
estações de montanha — Itatiaia, Morro da Igreja, Campos do Jordão — antes de
ir para a tela.

O efeito é visível e é bom sinal de que os dados estão certos: a estação mais
fria do país em julho é **Itatiaia (RJ), a 2.450 m** — não uma estação gaúcha.

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

## Fronteiras dos outros países

O globo da tela de abertura desenha o mundo por trás do Brasil. Esse contorno
não tem nada a ver com o modelo — é cenário — e vem do **Natural Earth**,
escala 1:110m: <https://www.naturalearthdata.com>. É domínio público (CC0),
então vai junto com o projeto, reduzido a 53 KB por `dados/baixar_mundo.py`.


## Fronteiras dos estados (camada dos mapas)

A divisa das 27 unidades federativas, desenhada por cima do mapa quando se liga
a camada "destacar as fronteiras dos estados".

```
python dados/baixar_malha_estados.py     ->  dados/malha_estados.json  (87 KB)
```

Vem da mesma API de malhas do IBGE que a malha municipal, e na mesma qualidade
(`qualidade=minima`, coordenadas arredondadas em 3 casas). Isso não é detalhe:
as duas são desenhadas uma por cima da outra, e simplificações diferentes
fariam a linha do estado passar ao lado da divisa do município — uma fresta
discreta no país inteiro e gritante quando a câmera desce num estado. O teste
`test_as_duas_malhas_batem_no_continente` trava essa condição.

### Por que não somar os municípios

A fronteira de um estado é, em tese, a soma das fronteiras dos municípios dele,
e o projeto já tem os 5.570. Só que desenhar com traço grosso os municípios de
um estado desenha junto **todas as divisas internas**, que é o contrário do que
a camada quer mostrar. Somar os polígonos de verdade é uma união geométrica:
cara e cheia de casos de borda. 87 KB resolvem sem conta nenhuma.

### A exceção: as ilhas oceânicas

A malha de UF do IBGE não traz as ilhas; a municipal traz. Na prática, Fernando
de Noronha (distrito de Pernambuco, a -32,4° de longitude) aparece no mapa
pintado com seu risco, mas sem contorno de estado em volta. É a única diferença
entre as duas malhas, e está fixada em teste para não passar despercebida se
mudar.

## Relevo (a camada de altitude)

A altura do terreno em todo o Brasil, que a camada "relevo" usa para pintar a
altitude e calcular o sombreamento.

```
python dados/baixar_relevo.py     ->  dados/relevo_brasil.bin   (7,6 MB)
                                      dados/relevo_brasil.json  (metadados)
```

### De onde vem

Dos **terrain tiles** da Amazon (projeto Terrarium, herdado do Mapzen): uma
composição aberta de SRTM, ASTER, GMTED e levantamentos nacionais, distribuída
sem cadastro e sem chave em
<https://registry.opendata.aws/terrain-tiles/>. Cada tile é um PNG 256×256 em
que a cor não é cor nenhuma — é a altitude codificada:

```
altura_em_metros = vermelho * 256 + verde + azul / 256 - 32768
```

O script baixa os 225 tiles que cobrem o país no zoom 7, decodifica os PNGs
(sem Pillow: o projeto não depende dele, e um PNG sem entrelaçamento é
honestamente simples), reprojeta de Mercator para uma grade regular de latitude
e longitude e salva as altitudes como inteiros de 16 bits.

### O formato do `.bin`

Cru, sem cabeçalho: 2026 × 1976 inteiros de 16 bits little-endian, linha a linha
de norte a sul. Quem diz o tamanho é o `.json` ao lado. Em JSON o mesmo conteúdo
passaria de 25 MB e o navegador ainda teria de converter texto em número quatro
milhões de vezes; assim o JavaScript recebe o bloco e o lê como `Int16Array` sem
custo nenhum.

### Passo de 0,02° (~2,2 km)

É o dobro da resolução de que o mapa do país inteiro precisaria — e de
propósito. Num mapa do Brasil todo, 0,04° bastaria: são ~40° de largura em
1000 px, ou 25 px por grau, que é exatamente o que uma grade de 0,04° entrega.

Só que o mapa não fica parado no país inteiro: ele voa até o estado, e é lá que
o relevo interessa, com a serra ocupando a tela. Nesse zoom, 0,04° virava
borrão, e o modo 3D mostrava degraus de 4 km no lugar de encostas.

Quem preferir um repositório menor pode voltar à grade de 2 MB, que continua
boa para o mapa do país:

```
python dados/baixar_relevo.py --passo 0.04 --zoom 6
```

### Duas coisas que o arquivo não é

**Não mede cume.** Cada ponto é a média de ~2,2 km de terreno, então pico
estreito sai mais baixo que a altitude de placa: o Pico da Neblina, de 2.995 m,
aparece com cerca de 1.760 m. A camada serve para ver onde estão a serra, o
planalto e a planície — não para medir a altitude de um ponto. A interface diz
isso no rodapé da camada.

**Não tem o fundo do mar.** Os tiles trazem a batimetria, que chega a -4.000 m,
e o script zera tudo que está abaixo do nível do mar. Nenhum ponto do Brasil
fica abaixo dele, e manter a profundidade criaria um degrau de 4 km na linha da
costa — que no sombreamento vira um risco brilhante em cima de todo o litoral.

### O retângulo é maior que o país

A grade cobre de -74,5° a -34,0° de longitude e de 5,5° a -34,0° de latitude, o
que entra em países vizinhos: o ponto mais alto do arquivo tem 6.546 m e está
nos Andes argentinos, não no Brasil. O mapa recorta o desenho no contorno do
país, então isso não aparece — mas é por esse motivo que o campo dos metadados
se chama `altitude_maxima_grade_m`, e não "altitude máxima do Brasil".

---

## Rios e geografia por município

```bash
python dados/baixar_rios.py          # dados/rios_brasil.json      (0,5 MB)
python dados/preparar_geografia.py   # dados/geografia_municipios.csv (0,8 MB)
```

O primeiro baixa a rede de rios do **Natural Earth 1:10m** (domínio público) e
recorta no retângulo do Brasil: 185 trechos, 29 mil vértices, 100 rios
nomeados — Amazonas, Negro, Madeira, Tapajós, Xingu, Tocantins, São Francisco,
Paraná, Paraguai, Uruguai e afluentes grandes.

O segundo cruza três coisas que já estavam no repositório — a malha do IBGE, a
grade de relevo e os rios — e produz **uma linha por município**:

| Coluna | O que é |
| --- | --- |
| `latitude`, `longitude` | centroide do maior polígono do município |
| `area_km2` | área, pela fórmula do shoelace em quilômetros |
| `altitude_media_m` | média da grade de relevo dentro da fronteira |
| `altitude_minima_m` | o ponto mais baixo do município |
| `amplitude_altitude_m` | máxima menos mínima — o quanto o terreno varia |
| `declividade_m_por_km` | inclinação média entre células vizinhas |
| `distancia_rio_km` | do centroide até o vértice de rio mais próximo |
| `distancia_rio_grande_km` | idem, só para os rios de maior porte |

Conferência do resultado: a soma das áreas dá 8.493.683 km² contra os
8.510.000 km² oficiais (0,2% de diferença), Campos do Jordão sai com 1.556 m,
Manaus a 46 km de rio grande e Fortaleza a 533 km.

### O que estas colunas NÃO são

**Não são features do modelo.** Foram medidas em
[`experimentos/testar_geografia.py`](../experimentos/README.md) e não passaram
no critério: o ganho ficou em +0,1 ponto em oito anos, dentro do ruído. O
arquivo continua aqui porque é barato, é reprodutível e serve à próxima
tentativa — não porque o modelo o use.

### Duas limitações honestas

**Rio grande, não água.** Natural Earth 1:10m traz os rios principais. Córrego
de bairro — que é o que alaga a maioria das cidades pequenas — não está lá. A
variável mede "beira de rio grande".

**Distância do centroide.** Um município extenso, atravessado por um rio só na
ponta, aparece mais longe do que de fato está. Medir da fronteira seria mais
correto e bem mais caro.
