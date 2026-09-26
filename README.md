# Fecart 2026 — Previsão de Risco de Desastres Naturais

Sistema que estima o **nível de risco** (baixo, médio ou alto) de desastres
naturais por município brasileiro, a partir do histórico de ocorrências do
**Atlas Digital de Desastres** (S2iD / Defesa Civil), 1991–2025.

A previsão é servida por uma API e consultada por uma interface web.
Tudo roda **localmente**: o modelo é treinado e executado na própria máquina,
sem serviço pago, sem chave de API e sem enviar dados para a internet.

> **Base de dados:** real. 76 mil ocorrências registradas em 5.256 municípios,
> entre 1991 e 2025. A base bruta não vai para o Git (82 MB) — cada pessoa
> baixa uma vez e roda o script de preparação.

---

## Como rodar (primeira vez)

**1. Clonar e entrar na pasta**

```bash
git clone https://github.com/Joao5554/Fecart-2026-teste-2.git
cd Fecart-2026-teste-2
```

**2. Criar e ativar o ambiente virtual**

```bash
python -m venv .venv
```

```powershell
.venv\Scripts\activate
```

> Se aparecer *"a execução de scripts foi desabilitada neste sistema"*, rode
> uma vez e abra um novo terminal:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

**3. Instalar as bibliotecas**

```bash
pip install -r requirements.txt
```

**4. Subir o sistema**

```bash
uvicorn backend.app:app --reload
```

- Interface: **http://127.0.0.1:8000/app**
- Documentação da API: **http://127.0.0.1:8000/docs**

Pronto. **O modelo treinado vem junto no repositório** (1,3 MB), assim como o
histórico de ocorrências que a API consulta — não é preciso baixar a base do
Atlas nem treinar para apresentar o projeto.

---

## Treinar de novo (opcional)

Só é necessário para mexer no modelo ou nos dados. Para apenas rodar o
sistema, pule esta seção.

**1. Baixar a base do Atlas**

Baixe a base consolidada em <https://atlasdigital.mi.gov.br> (arquivo
`BD_Atlas_..._Consolidado.csv`) e salve em `dados/bruto/`. São 82 MB, e por
isso ela não fica no repositório.

**2. Preparar o dataset**

```bash
python dados/preparar_dados.py
```

**3. Treinar**

```bash
python treinamento/treinar_modelo.py
```

O treino sobrescreve `modelo/modelo.pkl`. Se o resultado for melhor, comite o
arquivo novo; se foi só um teste, desfaça com `git checkout modelo/`.

---

## Estrutura do projeto

| Pasta / arquivo                    | O que é                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| `src/esquema.py`                   | **Contrato de dados** — quais colunas, unidades e faixas        |
| `src/atlas.py`                     | Converte o Atlas bruto no dataset e calcula as features         |
| `src/carregar.py`                  | Lê o CSV e valida contra o contrato antes de treinar            |
| `src/caracteristicas.py`           | Features derivadas e pré-processamento (imputação + one-hot)    |
| `src/procedencia.py`               | Registra se o dataset veio da base real ou de dados sintéticos  |
| `src/odds_ratio.py`                | Razão de chances de cada variável (regressão logística)         |
| `src/validacao_temporal.py`        | Janela expansiva, divisão em três partes e escolha de parâmetros |
| `analise/avaliacao_modelo.py`      | Avaliação passo a passo, comentada — para estudar e apresentar  |
| `dados/preparar_dados.py`          | Gera `dados.csv` a partir da base bruta                         |
| `dados/preparar_silhueta.py`       | Reduz a malha do IBGE ao contorno do país, para o globo         |
| `dados/baixar_mundo.py`            | Baixa o contorno dos outros países (Natural Earth), para o globo |
| `dados/baixar_malha_estados.py`    | Baixa a divisa das 27 UFs (IBGE), para a camada de fronteiras   |
| `dados/baixar_relevo.py`           | Baixa a altimetria do Brasil, para a camada de relevo           |
| `dados/baixar_rios.py`             | Baixa a rede de rios principais (Natural Earth)                 |
| `dados/preparar_geografia.py`      | Altitude, declividade, área e distância do rio, por município   |
| `dados/README.md`                  | **Metodologia dos dados** e limitações — leitura obrigatória    |
| `treinamento/treinar_modelo.py`    | Treina, avalia e salva o modelo                                 |
| `backend/app.py`                   | API que serve as previsões                                      |
| `frontend/`                        | Interface web (HTML/CSS/JS puro, sem bibliotecas)               |
| `frontend/cenario.js`              | Globo e campo de vento animados, em canvas 2D                   |
| `frontend/relevo3d.js`             | O mapa inclinado em 3D, também em canvas 2D                     |
| `testes/`                          | Testes automatizados (`pytest`)                                 |
| `modelo/`                          | Saída do treino: `modelo.pkl` e `metadados.json`                |

`src/esquema.py` é a peça central: treino, API e testes leem dele, então nunca
há divergência entre o que o modelo aprendeu e o que a API aceita.

```bash
python -m src.esquema
```

---

## Como o problema foi modelado

Uma linha = **um município, em um mês, para um tipo de desastre**. O tipo entra
como variável de entrada, o que permite um único modelo cobrir os dez grupos
(inundação, deslizamento, seca, vendaval, granizo, incêndio florestal e outros).

As features são de três naturezas — **onde** (UF, região, tipo), **quando**
(mês, que carrega a sazonalidade) e **histórico** (o que já aconteceu ali).
Todas contam apenas o que ocorreu **antes** do mês previsto.

A metodologia completa — construção do rótulo, exemplos negativos e vazamento
temporal — está em [`dados/README.md`](dados/README.md).

---

## A janela de previsão, e até onde ela é honesta

A interface oferece de **setembro de 2026 a dezembro de 2027**. Meses
anteriores saíram da lista porque "prever" um mês que já passou não é
previsão — para isso existe a aba Histórico.

O limite de cima é mais interessante, e custou uma correção no código.

### O problema: janelas que varrem o vazio

Quatro das variáveis mais importantes contam o que aconteceu nos 12, 24 e 60
meses **anteriores** ao mês pedido. A base do Atlas termina em dezembro de
2025. Logo, ao pedir um mês de 2027, a janela de 12 meses cai inteira num
período sem registro nenhum, e as contagens viram zero — não porque o país
ficou seguro, mas porque o Atlas ainda não chegou lá.

O efeito foi medido em `experimentos/horizonte_previsao.py`, nos 18.980 pares
(município, tipo) com histórico:

| Mês pedido | 09/2026 | 12/2026 | 01/2027 | 06/2027 | 12/2027 |
| --- | --- | --- | --- | --- | --- |
| Municípios em risco alto | 13,0% | 11,9% | 9,7% | 3,4% | 4,8% |
| `ocorrencias_uf_grupo_12m` (média) | 14,5 | 4,8 | **0,0** | **0,0** | **0,0** |

O sistema anunciava um Brasil cada vez mais seguro quanto mais longe se
perguntasse. Era só o fim da base.

### A correção: a janela para onde os dados param

`src/atlas._ancora` faz as janelas pararem no último mês com registro. É a
hipótese padrão em previsão com variáveis defasadas — *o que não se observa
recebe a última observação disponível*. O mês-alvo continua valendo para tudo
que é sazonal: o mês do calendário, o seno, o cosseno, e quantas vezes aquele
desastre já aconteceu naquele mês.

Com a correção, a previsão volta a variar por **estação**, e não por distância:

| Mês pedido | 09/2026 | 12/2026 | 01/2027 | 06/2027 | 12/2027 |
| --- | --- | --- | --- | --- | --- |
| Antes | 13,0% | 11,9% | 9,7% | 3,4% | 4,8% |
| **Depois** | **12,8%** | **19,9%** | **29,3%** | **15,6%** | **19,9%** |

Janeiro passa a ser o pior mês do país, o que bate com a estação chuvosa.

> **A consequência honesta:** setembro de 2026 e setembro de 2027 recebem a
> **mesma** resposta. Sem dado novo entre os dois, não existe nada que os
> distinga — e inventar essa diferença seria inventar informação. Quando o
> Atlas for atualizado, a janela pode andar para frente; o teste
> `testes/test_horizonte.py` falha de propósito nesse dia, avisando.

O treino não mudou nada com isso: todo mês-alvo do dataset está dentro da
base, então a âncora nunca chega a atuar ali. O teste
`test_features_do_passado_nao_mudam_com_a_ancora` compara o dataset inteiro
gerado com e sem a correção, e exige que sejam idênticos.

---

## Resultados

### Como o modelo é avaliado

A base é dividida **em três partes, por ano** — nunca por sorteio:

| Conjunto | Anos | Linhas | Para quê |
| --- | --- | --- | --- |
| Treino | 2010–2019 | 111.098 | ajustar o modelo |
| **Validação** | 2020–2021 | 24.121 | escolher os hiperparâmetros |
| Teste | 2022–2025 | 51.869 | medir, **uma vez só** |

O conjunto de validação existe para uma razão específica: escolher a
profundidade das árvores olhando o teste transformaria o resultado em "o
melhor que consegui naquele teste", que é sempre melhor do que o modelo faria
em dados novos. Escolhidos os hiperparâmetros, a validação volta para o treino
(2010–2021) e só então o teste é usado.

### Desempenho no conjunto de teste (2022–2025)

| Métrica | Valor |
| --- | --- |
| Acurácia | 70,2% |
| Acurácia balanceada | 56,4% |
| F1 macro | 0,568 |
| Casos de risco **alto** identificados | **57,4%** |

### Validação walk-forward: o desempenho é estável?

Uma única divisão pode dar sorte. A validação por **janela expansiva** treina
até um ano e testa no seguinte, repetidamente — como o sistema seria usado:

| Treina até | Testa | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- | --- |
| 2017 | 2018 | 61,7% | 73,8% |
| 2018 | 2019 | 66,6% | 80,3% |
| 2019 | **2020** | **46,9%** | **32,3%** |
| 2020 | 2021 | 58,1% | 62,5% |
| 2021 | 2022 | 60,2% | 64,6% |
| 2022 | 2023 | 57,6% | 62,4% |
| 2023 | 2024 | 53,9% | 54,8% |
| 2024 | 2025 | 59,3% | 71,1% |
| | **média** | **58,1% ± 5,8** | **62,7% ± 14,6** |

**2020 é o pior ano de todos**, e por uma margem grande. O modelo treinado até
2019 não anteciparia o que aconteceu ali: a taxa de ocorrências registradas
salta de 20% (2019) para 29% (2020) e continua subindo. Parte é aumento real
de eventos, parte é melhora da notificação — e nenhum modelo baseado em
histórico prevê uma mudança na forma de registrar.

Esse é o resultado mais honesto do trabalho: o desempenho **varia com o ano**,
e apresentar só a média esconderia isso.

### Confiabilidade: a porcentagem quer dizer o quê?

Acurácia e confiabilidade são perguntas diferentes, e a interface mostra as
duas: o **selo** ("risco alto") é acurácia; a **porcentagem** ao lado é
confiabilidade. Um modelo pode acertar muito o selo e mentir na porcentagem.

A medida própria disso chama-se calibração, e está em
`experimentos/confiabilidade.py`. Entre os casos a que o modelo deu X% de
chance de risco alto, quantos foram de fato risco alto (teste 2022–2025):

| Faixa prometida | Casos | Prometido | Aconteceu | Desvio |
| --- | --- | --- | --- | --- |
| 0–10% | 19.303 | 4,5% | 4,4% | **−0,1%** |
| 10–20% | 10.631 | 14,6% | 11,5% | −3,1% |
| 20–30% | 6.284 | 24,6% | 16,9% | −7,7% |
| 40–50% | 2.832 | 44,8% | 27,8% | −17,0% |
| 50–60% | 2.064 | 54,7% | 34,6% | **−20,2%** |
| 70–80% | 1.468 | 75,0% | 59,0% | −16,0% |
| 90–100% | 1.589 | 93,4% | 83,6% | −9,7% |

| Resumo | Valor |
| --- | --- |
| Erro de calibração esperado (ECE) | **6,2%** |
| Escore de Brier | 0,1211 |
| Brier de quem responde sempre a média | 0,1541 |
| Taxa real de risco alto no teste | 19,0% |
| Média prometida pelo modelo | 25,2% |

**Onde o modelo é confiável:** na faixa baixa, que é a maior. Nos 19.303 casos
em que ele promete até 10%, acontece 4,4% — praticamente no ponto. Quando o
modelo diz "fique tranquilo", pode acreditar.

**Onde ele não é:** no meio da escala. Onde promete 55%, acontece 35%. É
otimista, e por dois motivos somados.

1. **De propósito.** O treino usa peso 6 para "alto" contra 1 para "baixo" —
   deixar de avisar um caso grave custa seis vezes mais que um alarme falso.
   Isso empurra a probabilidade para cima de caso pensado.
2. **Sem querer.** A taxa de risco alto sobe de **13,7%** (2010–2021, treino)
   para **19,0%** (2022–2025, teste). O modelo aprendeu um mundo e foi
   aplicado em outro.

Os dois efeitos são de sinais opostos e se cancelam em parte. Tirando os pesos:

| | Prometido | ECE | Brier | Risco alto detectado |
| --- | --- | --- | --- | --- |
| **Com pesos** *(produção)* | 25,2% | 6,2% | 0,1211 | **57,4%** |
| Sem pesos | 13,2% | 5,9% | 0,1169 | 34,2% |

Sem os pesos a porcentagem vira pessimista em vez de otimista, o ECE melhora
0,3 ponto — e a detecção de casos graves **cai de 57% para 34%**. Não vale a
troca. Calibrar depois do treino também foi testado, e piorou tudo (ver
[`experimentos/README.md`](experimentos/README.md), seção 2).

> **A ressalva que vale mais que todas:** os meses sem desastre foram
> **amostrados** (3 negativos por positivo). A "taxa real de 19%" é a taxa
> dentro do dataset, não a chance de um desastre acontecer em Manaus em
> janeiro. A porcentagem serve para **comparar e priorizar** municípios — não
> para apostar.

### Qual algoritmo, e por quê

O classificador é um **gradient boosting** (`HistGradientBoostingClassifier`).
Era um Random Forest até setembro de 2026, e a troca só foi feita depois de
medir: os dois foram comparados em **seis anos independentes**, cada um
treinando só com o passado e sendo testado num ano inteiro que nunca viu.

| Ano testado | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | média |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Random Forest | 62,2% | 47,4% | 52,1% | 56,5% | 54,5% | 50,5% | 53,9% |
| **Gradient boosting** | 64,0% | 46,6% | 54,4% | 58,0% | 55,7% | 50,9% | **54,9%** |

**+1,0 ponto em média, melhor em 5 dos 6 anos** (teste t pareado: p = 0,038
unilateral; teste dos sinais: p = 0,11). É um ganho pequeno, e o próprio
relatório em [`experimentos/README.md`](experimentos/README.md) discute o
quanto ele é frágil. Foi aplicado porque é consistente, não porque é grande —
e porque o arquivo do modelo caiu de 33,6 MB para **1,3 MB** de quebra.

O critério de aprovação (vencer em 4 dos 6 anos, com média positiva) foi
escrito antes de a medição rodar.

Os hiperparâmetros do boosting **não** passam por busca no treino: são os que
foram validados nos seis anos. Trocá-los depois seria substituir um modelo
medido por um não medido. Para reproduzir o modelo antigo:

```bash
python treinamento/treinar_modelo.py --modelo floresta
```

Aí a busca por parcimônia volta a valer: entre candidatos cuja diferença de F1
cabe na tolerância de 0,01 — ruído de amostra —, **vence o mais simples**.

**Como ler os números com honestidade.** A acurácia de 70% não é o número
importante: como 75% das linhas são "baixo", chutar sempre "baixo" já daria
mais que isso. O que importa num sistema de alerta é quantos casos graves o
modelo **pega** — 57,4% — e isso foi obtido pesando o erro: deixar de avisar
um risco alto custa mais caro que um alarme falso. Com pesos neutros, o modelo
acerta mais no total e detecta bem menos casos graves.

A classe `medio` é a mais difícil (recall 0,300), o que faz sentido: ela é
justamente a faixa ambígua entre "nada aconteceu" e "aconteceu algo grave".

O modelo aprendeu padrões coerentes com a realidade — a variável mais
importante é o tipo de desastre, seguida do tempo desde a última ocorrência no
município e da atividade recente na região.

---

## Por que a divisão é temporal, e não aleatória

Existe um script que percorre a avaliação passo a passo, com os blocos
comentados — serve para estudar e para apresentar:

```bash
python analise/avaliacao_modelo.py
```

Ele responde com números duas perguntas que sempre aparecem.

**"Qual proporção usar: 50/50, 70/30 ou 80/20?"** Nesta base, quase não muda:

| Treino / teste | Linhas de treino | Acurácia balanceada |
| --- | --- | --- |
| 50 / 50 | 93.544 | 65,9% |
| 70 / 30 | 130.961 | 66,4% |
| 80 / 20 | 149.670 | 66,6% |

Menos de 1 ponto entre a pior e a melhor. Com 187 mil linhas, metade da base
já são exemplos de sobra. A regra dos 80/20 vale mesmo é para bases pequenas.

**"E a divisão aleatória, serve?"** Aqui não — e a diferença é grande:

| Divisão | Acurácia balanceada | F1 macro |
| --- | --- | --- |
| Aleatória (`train_test_split`) | 66,4% | 0,645 |
| **Temporal** (treina ≤2021, testa ≥2022) | **55,3%** | **0,565** |

Os 11 pontos a mais da divisão aleatória são ilusão. Ela sorteia as linhas,
então o modelo treina com meses de 2024 e é avaliado em 2015 — usando o futuro
para prever o passado. Pior: o mesmo município aparece dos dois lados em meses
vizinhos, quase copiando a resposta.

**O projeto usa a divisão temporal**, e é dela que sai o número apresentado.
É menor, e é o único que descreve como o sistema funcionaria de verdade.

### E a padronização das variáveis?

Não é aplicada, e isso é decisão, não esquecimento. Árvores de decisão dividem
por limiares ("ocorrências > 3?"), então multiplicar uma coluna por mil não
muda divisão nenhuma — modelos de árvore são indiferentes à escala. Padronizar é
indispensável em modelos que somam coeficientes, e é exatamente o que a
análise de odds ratio faz na regressão logística.

---

## A chuva do INMET: um resultado negativo que ensina

O projeto incorporou os dados das estações automáticas do INMET — 10.691
arquivos de estação, 2000 a 2025, sem nenhuma falha de leitura. O resultado
foi o oposto do esperado, e é o achado mais interessante do trabalho.

### A chuva explica o desastre, e com folga

Nos municípios que têm estação própria, comparando meses com e sem ocorrência:

| Tipo de desastre | Risco baixo | Risco alto | |
| --- | --- | --- | --- |
| Hidrológicos — chuva máxima em um dia | 30,8 mm | **73,4 mm** | p ≈ 10⁻²³⁵ |
| Hidrológicos — chuva total do mês | 91,7 mm | **297,1 mm** | |
| Estiagem e seca — chuva do mês | 73,8 mm | **32,0 mm** | p ≈ 10⁻³² |

A associação é enorme e na direção certa, inclusive invertendo-se para a seca.
Não há dúvida de que a chuva causa o desastre.

### E mesmo assim não melhorou a previsão

| Modelo | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- |
| Sem clima | 55,2% | 56,0% |
| Com chuva do mês anterior | 55,0% | 56,1% |
| Com chuva do próprio mês *(só diagnóstico)* | 54,6% | 53,8% |

Nem a chuva do **próprio mês** ajuda — e essa é a linha que derruba a
explicação mais óbvia. Também não é problema de distância da estação: nas
linhas em que a medição vem do próprio município, o ganho é de +0,3 ponto,
dentro do ruído.

### Por que isso acontece

**A informação já estava lá, por outro caminho.** O modelo sabe o mês, sabe
quantas vezes aquele tipo de desastre já ocorreu naquele mês do calendário
naquele município, e sabe quanta coisa aconteceu na UF nos últimos 12 meses.
Isso já é, indiretamente, "está chovendo na região agora". A chuva medida
confirma o que o modelo deduzia, mas não acrescenta.

**E o que faltava, o dado mensal não tem.** Um deslizamento acontece por causa
de 100 mm em seis horas, não de 300 mm ao longo de trinta dias. Ao agregar
por mês, o extremo que causa o desastre se dissolve na média.

### O que isso significa

Explicar e prever são coisas diferentes. Saber que chuva forte causa enchente
não permite prever a enchente do mês que vem — para isso seria preciso prever
a **chuva** do mês que vem, o que é meteorologia, não histórico.

O caminho para a chuva de fato ajudar é mudar a resolução: prever por semana
ou por dia, usando a data exata que o Atlas registra e a chuva acumulada em
24, 48 e 72 horas. Aí o extremo aparece.

As variáveis climáticas ficaram no modelo — ele as usa (21% da importância
total) e a estabilidade entre os anos melhorou um pouco (desvio de 5,7% para
4,9%). Mas o ganho de acurácia foi nulo, e o projeto declara isso.

---

## Odds ratio: quanto cada variável multiplica o risco

A importância das variáveis diz **quanto** cada uma ajudou a separar os casos
— mas não diz a **direção** nem o **tamanho** do efeito. Para isso o projeto
ajusta também uma **regressão logística** sobre os mesmos dados e reporta a
razão de chances:

    OR = 2,0  ->  a chance dobra
    OR = 1,0  ->  a variável não altera a chance
    OR = 0,5  ->  a chance cai pela metade

São dois modelos com papéis diferentes, de propósito: o boosting **prevê** (é o
que a API usa), a regressão **explica** (é o que se apresenta e se discute).

### Resultado — chance de o desastre ser grave

| Variável | OR | IC 95% |
| --- | --- | --- |
| Ser estiagem/seca | 4,45 | 3,95 – 5,00 |
| Ser chuva intensa | 3,61 | 3,21 – 4,05 |
| Ser inundação | 2,79 | 2,47 – 3,16 |
| Ser enxurrada | 2,55 | 2,26 – 2,88 |
| Ocorrências do tipo na UF (12 meses) | 1,40 | 1,38 – 1,41 |
| Ocorrências no mesmo mês do calendário | 1,38 | 1,37 – 1,40 |
| Região Nordeste | 1,36 | 1,26 – 1,46 |
| Ocorrências nos últimos 12 meses | 0,86 | 0,84 – 0,88 |

AUC da regressão: 0,785. Valores numéricos por desvio-padrão.

Rode `python treinamento/treinar_modelo.py` para ver a tabela completa, ou
consulte `GET /modelo/odds-ratio`.

### Cuidados estatísticos aplicados

Um odds ratio errado é perigoso porque *parece* certo — sai com intervalo de
confiança e p-valor, e ninguém desconfia. Quatro cuidados no código:

- **Multicolinearidade.** `ocorrencias_12m`, `_24m`, `_60m` e o total chegam a
  0,88 de correlação. O VIF mede a redundância e remove as variáveis acima do
  limite, uma por vez.
- **Janelas aninhadas.** A janela de 60 meses *contém* a de 24, que contém a de
  12. Na mesma regressão isso inverte o sinal dos coeficientes. Elas são
  substituídas por faixas disjuntas (0–12, 13–24, 25–60 meses).
- **Escala.** Meses, pessoas e reais não são comparáveis; tudo é padronizado, e
  o OR lê-se como "por 1 desvio-padrão a mais".
- **Separação.** Categoria rara que prevê o desfecho perfeitamente produz OR
  infinito. Esses casos saem marcados como *instáveis* e nunca como
  significativos.

### Um achado que vale discutir na apresentação

`ocorrencias_12m` tem OR **0,86** para gravidade: entre os meses em que houve
desastre, os municípios com mais ocorrências recentes tendem a ter eventos
**menos** graves. Não é erro — nos dados, a taxa de risco alto cai de 60% (sem
ocorrência nos 12 meses anteriores) para 5% (seis ou mais).

A leitura provável: lugares com eventos crônicos e frequentes registram muitos
episódios pequenos, enquanto lugares onde o desastre é raro registram
principalmente as catástrofes.

### Como esta análise consertou o projeto

O odds ratio foi sugerido pelo professor de estatística, e a primeira rodada
apontou algo implausível: ocorrências recentes apareciam **reduzindo** o risco
de haver desastre. A investigação mostrou que a culpa era do ETL, não da
estatística: os exemplos negativos eram sorteados com cota por município
(3 para cada positivo daquele município), o que travava a taxa de risco em
exatamente 25% para todo mundo — apagando a diferença entre lugares perigosos
e tranquilos.

Com o sorteio global, a taxa voltou a variar de 4% a 100% conforme o município,
e o modelo melhorou junto: a detecção de casos graves subiu de 48,9% para
**56,2%**. Nenhuma métrica de acurácia tinha denunciado esse defeito.

---

## Como o projeto se protege de erro silencioso

- **Sem vazamento temporal.** As features de um mês nunca usam aquele mês nem o
  futuro, e um teste confere isso linha a linha.
- **Divisão temporal em três partes.** Treino, validação e teste cortados por
  ano. Um teste "espião" registra quais anos cada etapa enxergou e falha se a
  escolha de hiperparâmetros tocar no conjunto de teste.
- **Validação walk-forward.** Oito janelas independentes, com desvio-padrão e
  o pior ano reportados — não só a média.
- **Modelo final com a base inteira.** Medido o método, o `.pkl` que vai para
  o disco é retreinado com 2010–2025. Os metadados registram isso, para
  ninguém ler as métricas como se fossem daquele objeto.
- **Procedência dos dados.** O dataset carrega um registro com hash SHA-256 da
  origem; a API informa se o modelo foi treinado com base real ou sintética.
- **Assinatura do esquema.** Cada modelo guarda a impressão digital do contrato
  de dados com que foi treinado. Mudou a coluna e esqueceu de retreinar? A API
  **recusa** o modelo antigo em vez de responder besteira.
- **Um único cálculo de features.** Treino e consulta da API passam pela mesma
  função (`src/atlas.calcular_features`), e um teste garante que produzem
  números idênticos.
- **Pipeline salvo inteiro.** As transformações vão dentro do `.pkl`.

---

## A API

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/` | Estado da API e do modelo |
| `GET` | `/esquema` | Contrato de dados (quais campos enviar) |
| `GET` | `/modelo/info` | Métricas e procedência do modelo carregado |
| `GET` | `/modelo/odds-ratio` | Quanto cada variável multiplica a chance de risco |
| `POST` | `/modelo/recarregar` | Recarrega o `.pkl` sem reiniciar o servidor |
| `GET` | `/municipios` | Busca municípios por nome (ignora acento) ou UF |
| `GET` | `/municipios/{ibge}/historico` | Ocorrências já registradas no município |
| `POST` | `/prever/municipio` | **Previsão a partir de município, tipo e mês** |
| `POST` | `/prever` | Previsão informando todas as features manualmente |
| `POST` | `/prever/lote` | Várias previsões de uma vez |
| `GET` | `/mapa/malha` | Fronteiras dos 5.570 municípios (GeoJSON do IBGE) |
| `GET` | `/mapa/estados` | Divisa das 27 unidades federativas (GeoJSON do IBGE) |
| `GET` | `/mapa/relevo` | Onde fica e como ler a grade de altitudes |
| `GET` | `/mapa/relevo.bin` | A grade de altitudes, crua (1 milhão de inteiros de 16 bits) |
| `GET` | `/mapa/brasil` | Risco de todos os municípios de uma vez — é o que pinta o mapa |
| `GET` | `/mapa/capitais` | As 27 capitais, com o ponto onde marcá-las no mapa |
| `POST` | `/mapa/risco` | GeoJSON de pontos, para quem já tem coordenadas |
| `GET` | `/historico/anos` | Quanto cada ano de 1991 a 2025 registrou |
| `GET` | `/historico/ano/{ano}` | **O que aconteceu num ano, pronto para o mapa** |
| `GET` | `/clima/chuva` | Chuva medida em cada estação do INMET, num mês ou num ano |

O endpoint que a interface usa é o `/prever/municipio`: quem consulta informa
apenas **onde, o quê e quando**, e o backend calcula as quinze variáveis
históricas a partir do Atlas.

Os dois endpoints de `/historico` são os únicos que **não passam pelo modelo**:
respondem só o que o Atlas registrou. A separação é proposital — o mapa de
risco mostra uma estimativa, que pode errar; o mapa por ano mostra um fato.

---

## A interface

Servida pela própria API em **http://127.0.0.1:8000/app**, em HTML, CSS e
JavaScript puros — sem framework e sem CDN, para o projeto inteiro rodar
offline.

**Três palcos, não uma página que rola.** A interface é uma sequência de telas
cheias — abertura, mapas e despedida —, e só uma fica visível por vez. Quem
manda é o atributo `data-palco` no `<body>`; o CSS cuida das transições. Os
botões "Abrir os mapas", "Encerrar" e "Começar de novo" percorrem o caminho,
que é o mesmo de uma apresentação: abre, mostra, encerra, recomeça.

**Cenário animado, sem biblioteca.** A abertura e a despedida têm um globo
girando ao fundo; o palco dos mapas, um campo de vento com ciclones. Os dois
são canvas 2D escritos à mão em `frontend/cenario.js`: o globo é uma projeção
ortográfica com meridianos, atmosfera e as capitais pulsando sobre o país; o
vento é um sistema de partículas seguindo um campo de velocidade, com alguns
vórtices somados por cima — girando no sentido horário, que é o do hemisfério
sul. Uma biblioteca 3D custaria centenas de KB baixados de fora só para o
plano de fundo, e o projeto inteiro roda offline. O contorno do Brasil que o
globo desenha sai de `dados/preparar_silhueta.py`, que reduz uma vez os 5.570
municípios da malha do IBGE a algumas centenas de pontos. Só um dos dois
cenários desenha por vez: o que está atrás de um palco invisível fica pausado.

O resto do planeta vem de `dados/baixar_mundo.py`, que reduz os países do
Natural Earth 1:110m a 53 KB. Eles existem para dar escala ao Brasil — um país
sozinho numa esfera azul podia ter qualquer tamanho e estar em qualquer lugar
— e por isso são desenhados apagados, em dois tons: a América do Sul um pouco
mais clara que os outros continentes, porque é a vizinhança contra a qual se
lê onde o país começa e termina. O Brasil é o único com halo.

**Dois mapas, um em cada aba.** "Previsão" mostra o risco estimado para cada
município; "Histórico" mostra o que o Atlas registrou, ano a ano. As escalas
de cor são diferentes de propósito — uma conta risco, a outra conta
ocorrências, e duas escalas iguais para coisas diferentes seriam o jeito mais
fácil de alguém confundir uma previsão com um fato.

**O voo até o município.** Consultar uma cidade não troca o mapa: move a
câmera. Os dois mapas grandes são sempre desenhados com o país inteiro, num
sistema de coordenadas fixo, e aproximar é uma transformação CSS aplicada ao
elemento que contém as três camadas (mapa, chuva e capitais) de uma vez — uma
só matriz move as três, e elas nunca saem de registro. A câmera passa pelo
estado antes de fechar no município: sem essa parada o Brasil vira um borrão e
quem assiste perde a referência de onde a cidade fica. A escala cresce em
progressão geométrica, e não linear, porque dobrar de 1 para 2 e dobrar de 40
para 80 têm de parecer o mesmo movimento. O primeiro cálculo de cada tipo e
mês leva alguns segundos no servidor, mas o voo não espera por ele: onde fica
o município é a malha que diz, e ela não muda com a pergunta — a cor do risco
chega por baixo quando ficar pronta.

**O destaque de quem foi escolhido.** O estado acende junto com a parada nele,
e o município ganha um anel ao pousar. O destaque do estado é feito por
subtração: uma camada cobre o mapa inteiro e tem, recortado nela, o buraco no
formato exato do estado — o caminho é o retângulo do mapa seguido dos
polígonos daquela UF, com `fill-rule="evenodd"`. A borda do buraco é, por
construção, a fronteira real do estado, sem precisar calcular a união de
centenas de municípios. O anel do município é mais simples, mas precisa que
ele seja o último `<path>` do SVG: não existe `z-index` em SVG, e no meio da
malha o traço do vizinho comia metade do anel.

**Um tema só, o escuro.** Os palcos têm um céu estrelado e um campo de vento
por trás, e a interface clara sobre eles apagava a animação inteira — o modo
claro existia e foi retirado. Com ele saíram o botão do topo, o script do
`<head>` que lia a escolha antes da primeira pintura e o bloco de variáveis
alternativo: a paleta inteira vive no `:root`, e nenhuma regra precisa saber
que um dia houve tema. As cores dos dados (verde, amarelo, vermelho) sempre
foram de fora dessa discussão: significam nível de risco, e o `app.js` as lê
do CSS pelo nome.

**Capitais em destaque.** O mapa pinta 5.570 municípios e não escreve nenhum
nome: sem referência nenhuma, quem olha vê manchas de cor e não sabe onde está
olhando. Os três mapas marcam as 27 capitais — ponto, nome e o contorno do
município reforçado — e isso basta para o olho se situar. O ponto vem do
centroide do maior polígono do próprio município, calculado a partir da mesma
malha que desenha o mapa, então cai sempre dentro do contorno que ele nomeia.
Os nomes se desviam uns dos outros: no Nordeste as capitais ficam a poucos
graus de distância e, escritas todas do mesmo lado, "Recife", "Maceió" e
"Aracaju" sairiam empilhadas. Um interruptor desliga a camada, para quando o
nome cobre justamente o município que se quer olhar.

**Camada de chuva medida.** Um interruptor ao lado de cada mapa sobrepõe a
chuva registrada pelas estações automáticas do INMET, no estilo dos mapas de
tempo. O ponto delicado é de onde vem o número: no `clima_mensal.csv`, que
alimenta o modelo, **92% das linhas carregam a chuva de uma estação de outro
município** — só 8% do país tem estação própria. Isso serve como variável de
entrada, mas pintar município a município com esses valores desenharia uma
precisão que não existe. Por isso a camada interpola entre as **662 estações
reais** e desenha os marcadores por cima: quem olha vê a mancha e vê de onde
ela veio. O rodapé sempre diz de que período é a medição — o mapa de risco
prevê um ano que ainda não aconteceu, e a chuva ao lado dele é sempre de
outro momento.

Três decisões fazem essa camada parecer um mapa de tempo, e não uma mancha
solta sobre o desenho:

- **A mancha é recortada no contorno do mapa.** Interpolar entre estações
  espalha valor por todo o retângulo, inclusive sobre o mar e sobre os estados
  fora do recorte. A máscara é o que impede a camada de afirmar chuva onde não
  há nem terra nem estação.
- **A cor é contínua.** As faixas da legenda ("60 a 120 mm") continuam sendo
  as mesmas cores, mas o valor entre duas faixas é interpolado: pintar faixa a
  faixa desenhava degraus onde a chuva é contínua, e degrau no meio da mancha
  parece fronteira de dado.
- **A opacidade acompanha o volume.** Onde choveu pouco a camada quase some e
  deixa o mapa aparecer. Com opacidade fixa, o "quase não choveu" cobria o
  mapa com a mesma força do "choveu 400 mm", e o olho lia área coberta em vez
  de intensidade.

A legenda deixou de ser uma fileira de quadradinhos iguais — que dizia que
"0 a 5 mm" ocupa tanto da escala quanto "300 a 450 mm" — e virou uma barra
contínua, em que a posição de cada marca é o próprio valor.

**Camada de vento predominante.** Outro interruptor sobrepõe o vento: milhares
de partículas correndo pelo campo e deixando rastro, do jeito que mapas de
vento fazem. A direção e a velocidade vêm das mesmas estações automáticas do
INMET, reduzidas a uma linha por estação e mês em `dados/preparar_vento.py`.
A cor de cada rastro é a velocidade, na escala da legenda.

A camada está nos **três mapas que escolhem um mês**, e não no mapa do
histórico, que escolhe um ano. Vento anual não existe como grandeza útil: a
direção predominante de janeiro e a de julho podem ser opostas, e a média das
duas não descreve nenhum dos dois.

Três coisas valem ser ditas sobre ela:

- **É climatologia, não previsão de curto prazo.** "Março" devolve o março
  típico, apurado sobre cinco anos de medição — não os próximos dias. É o que
  casa com o resto do sistema, que também estima risco por mês: perguntar
  "vendaval em fevereiro" e receber o vento que fevereiro costuma trazer é a
  mesma pergunta pelos dois lados. Um campo como o do Windy sai de um modelo
  global rodado quatro vezes ao dia e exigiria internet a cada abertura.
- **A média é vetorial, e isso não é detalhe.** Ângulo não se soma: a média
  aritmética de 350° e 10° dá 180°, o rumo oposto ao de duas medições que
  quase coincidem. Cada hora vira um vetor antes de qualquer média, e é por
  isso que a API entrega `u` e `v` prontos — quem anima um campo soma vetores.
  O erro seria silencioso, e por isso tem teste próprio.
- **A animação corre mais rápido que o vento.** Na escala do mapa, o ar real
  levaria horas para cruzar um estado e a tela pareceria parada. O movimento
  mostra o **rumo**; a magnitude quem carrega é a cor.
- **As partículas vivem no mapa, mas são desenhadas na tela.** O canvas do
  vento fica *fora* da câmera: dentro dela ele seria ampliado como bitmap, e um
  desenho de 1000x820 esticado a 5x é borrão — pedir linha mais fina para
  compensar só produz linha mais fraca, porque abaixo de um pixel do buffer não
  existe traço, existe cinza. Fora da câmera, o canvas tem o tamanho da tela em
  pixels reais e é o desenho que recebe a transformação. O traço sai com um
  pixel de verdade em qualquer aproximação, e a densidade não muda com o zoom,
  porque as partículas nascem só dentro do que está à vista.

A legenda traz ainda a **constância média** do mês: perto de 1, o vento soprou
sempre para o mesmo lado — é o caso dos alísios do Nordeste, acima de 0,90 em
Fortaleza e Natal. Perto de 0, ele girou tanto que a predominante é quase um
empate, como no Sul em julho. Sem esse número, um alísio firme e um mês de
vento caótico desenhariam a mesma seta.

**Camada de temperatura — o mapa de calor.** O terceiro interruptor pinta o
campo térmico do país, do jeito que o Windy pinta o dele: violeta e azul para
o frio, verde para o ameno, amarelo e laranja para o quente, vermelho para o
extremo. É a convenção meteorológica, e não uma escolha estética — quem já viu
um mapa de temperatura lê este sem legenda. Os números vêm das mesmas estações
automáticas do INMET, reduzidas por `dados/preparar_temperatura.py`.

Ela está nos **quatro mapas**, e responde a três perguntas diferentes conforme
quem pergunta:

| Quem pede | O que recebe |
| --- | --- |
| Os três mapas de previsão (pedem só o mês) | O mês **típico**, apurado sobre 2021–2025 |
| O mapa do histórico (pede um ano) | A média daquele ano, de fato |
| A API, com ano e mês | Aquele mês daquele ano, exatamente |

A diferença para o vento é que aqui a média de vários anos continua
significando alguma coisa: temperatura é média, e média de médias é média. A
direção predominante de um ano inteiro não descreve mês nenhum — por isso o
vento não está no mapa do histórico, e a temperatura está.

Quatro decisões separam este desenho de uma interpolação qualquer:

- **Ela é cheia, e fica por baixo das outras duas.** Chuva é *intensidade*:
  existe "não choveu", e onde chove pouco a camada se apaga de propósito.
  Temperatura não tem zero nem ausência — todo ponto do país tem uma, sempre —,
  então a opacidade é constante, e apagá-la onde faz frio diria que ali falta
  dado. Por ser o único campo sem buraco, ela é o fundo sobre o qual a chuva e
  o vento continuam legíveis; por cima, seria tinta opaca que apagaria as duas.
- **Sem olho de boi e sem circunferência.** São dois artefatos que aparecem no
  desenho e não nos números. Sem um piso de distância, o peso da interpolação
  vai a infinito em cima de cada estação e cada uma vira uma bolha chapada com
  anel em volta. Sem um corte suave, o limite do alcance vira uma
  circunferência visível — e num campo cheio não há transparência que a
  disfarce. O piso resolve o primeiro; uma gaussiana que leva o peso a quase
  zero na borda do raio resolve o segundo.
- **O índice espacial, e o que ele custou para valer a pena.** Comparar cada
  célula da grade com todas as estações são 14 milhões de distâncias por
  desenho, quase todas resultando em "longe demais". Distribuir as estações em
  caixas do tamanho do raio derruba isso para 2,6 milhões — mas a primeira
  versão **empatou** com a varredura burra, porque juntar as nove caixas
  vizinhas alocava um array por célula, e alocar custa o que se economizou.
  Guardando a lista por caixa, as milhares de células que caem na mesma caixa
  reaproveitam a mesma lista, e aí o ganho aparece: ~24 ms contra ~46 ms, com
  uma grade mais fina que a da chuva.
- **Ela não corrige a altitude, e diz isso.** O ar esfria cerca de 6,5 °C a
  cada 1.000 m, e a interpolação não sabe onde estão as serras: entre uma
  estação de praia e uma de montanha, ela desenha a transição como se o relevo
  fosse uma rampa. Perto de cada estação o número é o medido; longe de todas, é
  estimativa — e é o que o rodapé da camada explica. Corrigir de verdade
  exigiria reduzir cada estação ao nível do mar antes de interpolar; a grade de
  altitude que isso pede passou a existir com a camada de relevo, e ligar as
  duas está anotado como próximo passo em `dados/README.md`.

O dado também serve de teste de sanidade do próprio encanamento: a estação mais
fria do Brasil em julho é **Itatiaia (RJ), a 2.450 m, com 5,6 °C** — seguida de
Morro da Igreja, São Joaquim e Campos do Jordão —, e a mais quente é
**Manaus, com 28,6 °C**. Se latitude e longitude entrarem trocadas em qualquer
ponto do caminho, esse ranking desmonta, e nenhuma checagem de formato notaria.

**Fronteiras dos estados.** A divisa das 27 unidades federativas vem desenhada
por cima do mapa, **ligada por padrão** — como as capitais, e ao contrário das
camadas de dado, que começam desligadas. Parece supérfluo, já que o mapa tem os
5.570 municípios, mas não é: sem ela, uma mancha vermelha no meio do país não
diz de que estado é, e a pergunta seguinte de quem olha um mapa de risco é
sempre "onde fica isso?". Quem não quiser, desliga; trocar de mapa a devolve
ligada, porque fronteira é parte do mapa e não informação sobreposta a ele.

A linha **vai dobrada**: um traço escuro largo por baixo e um branco fino por
cima. Uma linha clara sozinha some sobre o amarelo do risco médio e sobre o
claro do relevo alto; uma escura sozinha some sobre o fundo e sobre o vermelho.
O par aparece em qualquer lugar do mapa — é o mesmo truque do marcador das
capitais. E a cor é branca de propósito: verde, amarelo e vermelho já
significam risco, e o ciano já significa "este é o estado escolhido". Uma
quarta cor de dado faria o olho ler dado onde só há referência geográfica.

**Camada de relevo.** Um interruptor pinta a altitude do terreno, com a escala
hipsométrica dos atlas (verde na planície, marrom na montanha) e sombreamento
de relevo por cima. O dado é real: 2.026 × 1.976 altitudes medidas, vindas dos
*terrain tiles* abertos da Amazon (SRTM, ASTER e GMTED), baixadas uma vez por
`dados/baixar_relevo.py` e servidas como um bloco de 7,6 MB que o navegador lê
direto como `Int16Array`.

Três decisões fazem essa camada funcionar:

- **Ela fica por baixo do mapa, e é a única que fica.** Todas as outras camadas
  cobrem o mapa de risco; o relevo é o chão, e o risco é uma propriedade do
  município que está em cima dele. Então aqui o desenho é o oposto: o mapa é
  que fica translúcido e deixa o terreno aparecer por baixo da sua cor, como
  qualquer atlas imprime um mapa temático sobre relevo. Resolve de graça o
  problema que as outras camadas enfrentam — o risco não precisa "sobreviver
  como contorno", continua sendo a mancha de cor.

- **O sombreamento é calculado no navegador, uma vez.** Ele simula um sol baixo
  a noroeste e pergunta, para cada ponto, o quanto a encosta ali está virada
  para essa luz. O noroeste não é capricho: o olho humano interpreta sombra
  supondo luz vinda de cima e da esquerda, e um mapa iluminado do sudeste
  produz a *ilusão do relevo invertido*, em que vale vira morro. A inclinação
  entra multiplicada por 6 — exagero declarado, a mesma licença que os mapas de
  relevo tomam há um século, e sem ela o Brasil, que é manso, sairia liso.

- **Um grau de longitude não é um grau de latitude.** No Chuí ele vale 83% do
  que vale no Equador. Tratar os dois como iguais entortaria o sombreamento
  progressivamente de norte a sul, e a serra gaúcha sairia mais íngreme do que
  é só por estar longe da linha do Equador.

A camada **não mede cume**: cada ponto é a média de ~2,2 km de terreno, então
pico estreito sai mais baixo que a altitude de placa — o Pico da Neblina, de
2.995 m, aparece com cerca de 1.760 m. Serve para ver onde estão a serra, o
planalto e a planície, e o rodapé da camada diz isso na tela.

**Modo 3D.** Nos dois mapas grandes, um interruptor inclina a cena e levanta o
terreno: o mesmo mapa, girável com o mouse, com a roda aproximando. O desenho
mora em `frontend/relevo3d.js` e é feito em canvas 2D — sem three.js, sem
WebGL, sem CDN, como o resto do projeto. O globo da tela de abertura já fazia
projeção 3D à mão; aqui é a mesma ideia aplicada a um mapa de altitudes.

Quatro decisões sustentam essa cena:

- **A superfície veste o mapa plano.** Antes de desenhar, o app pinta o mapa 2D
  num canvas fora da tela — terreno por baixo, risco translúcido por cima — e
  usa essa imagem como textura. É o que faz o 3D mostrar a *mesma* informação
  do mapa, e não um relevo bonito e mudo ao lado dele: quem gira a cena continua
  olhando o risco, agora sabendo se o município está na serra ou na várzea. O
  recorte da textura no contorno do país tem uma segunda função além da
  estética — onde ela fica transparente, o quadrilátero não é desenhado, e o
  terreno sai com o formato do Brasil em vez de uma placa retangular.

- **Os quadriláteros são pintados de trás para frente.** É o algoritmo do
  pintor, e dá oclusão correta sem nenhum buffer de profundidade por pixel. A
  ordem sai de uma ordenação por contagem em 1.024 gavetas de profundidade, e
  não de um `sort`: são dezenas de milhares de quadriláteros por quadro, e
  n·log(n) com comparador derrubaria a taxa de quadros durante o arrasto.

- **A malha afina quando a cena para.** Girando, ela usa células maiores;
  parada, volta à resolução cheia. Ninguém repara na malha grossa enquanto a
  cena está em movimento, e girar com cinquenta mil células engasgaria.

- **A cena é reduzida para tamanho 1 antes de qualquer conta de câmera.** Não é
  elegância: a distância da câmera vale 2,6, e sem a redução ela ficaria
  comparável a uma janela de quarenta graus de largura. O divisor da
  perspectiva cruzaria o zero no meio do mapa e metade dos pontos sairia
  projetada do lado errado da tela. Foi exatamente assim que a cena apareceu na
  primeira vez que rodou: um leque de triângulos em vez de um país.

O exagero vertical é inevitável e é declarado no rodapé. O Brasil tem 4.300 km
de largura e 2.995 m de altura máxima — na escala real, o relevo do país
inteiro seria uma folha de papel, 0,07% da largura. A cena calcula o exagero
para o ponto mais alto da janela ocupar cerca de 17% da largura dela, o que
mantém a montanha visível tanto no país inteiro quanto num estado só, e mostra
o número usado (91× no Brasil inteiro, bem menos num estado).

**O município no mapa, dentro da consulta.** Logo abaixo do formulário, o
contorno real do município consultado, ampliado e pintado com o risco previsto
para o mês escolhido — a mesma resposta do selo, no lugar em que a pergunta foi
feita. Não custa previsão nenhuma: a cor e a probabilidade já vieram na resposta
que preencheu o selo, e o único download é o da malha, compartilhada com os
outros mapas. Aceita as duas camadas, e o contorno leva a cor do risco em vez do
azul-marinho dos outros mapas: com a chuva ligada o preenchimento clareia, e
aqui o município é o único polígono da tela — no traço, a cor não some.

**A cidade e a região.** Depois de uma consulta, um mapa mostra o município
consultado em destaque e os vizinhos, cada um com o risco previsto para o mesmo
mês e o mesmo tipo. Ele e o gráfico dos doze meses são pedidos **em paralelo**:
o gráfico custa doze previsões, e enfileirado atrás dele o mapa da cidade
demorava quase um minuto para aparecer — tempo suficiente para quem consultou
concluir que a seção não existe.

**Mapa por ano.** Escolha um ano de 1991 a 2025 e veja onde os desastres foram
registrados, com filtro por tipo e por estado. A escala de cor conta
ocorrências (cinco faixas, do amarelo ao vinho) e é deliberadamente diferente
da escala de risco: duas escalas iguais para coisas diferentes seriam o jeito
mais fácil de alguém confundir uma previsão com um fato. Municípios sem
registro no ano ficam cinza, não verdes — "não aconteceu nada" e "não sabemos"
não são a mesma informação.

---

## Levar o projeto para outro computador

**Com internet, o caminho mais simples é o `git clone`** dos passos acima: o
modelo já vem junto, então em três comandos o sistema está no ar.

Se o computador não tiver internet (ou bloquear o `pip`), monte um pacote e
leve no pendrive. A pasta inteira passa de 500 MB, mas quase tudo é
descartável na hora de apresentar:

```bash
python ferramentas/preparar_apresentacao.py
```

Gera a pasta `apresentacao/` com **16 MB** — cabe em qualquer pendrive. Dentro
dela vai um `LEIAME.md` com o passo a passo para quem for rodar. (Eram 28 MB
enquanto o modelo era um Random Forest; o boosting sozinho economizou 12 MB.)

Se o computador da escola não tiver internet (ou bloquear o `pip`), inclua as
bibliotecas junto:

```bash
python ferramentas/preparar_apresentacao.py --com-bibliotecas --zip
```

São 93 MB compactados, e a instalação passa a funcionar offline.

### O que fica de fora, e por quê

| Item | Tamanho | Por que não vai |
| --- | --- | --- |
| `.venv/` | 336 MB | Recriado com `pip`; ambiente virtual não se copia entre máquinas |
| `dados/bruto/` | 82 MB | Base crua do Atlas — só serve para **treinar** de novo |
| `dados/dados.csv` | 24 MB | Dataset de treino — o modelo já está pronto |

### E cortar anos antigos da base, para aliviar?

Foi medido, e **não compensa**. O período do dataset afeta bastante a
qualidade, enquanto o tamanho do arquivo depende do algoritmo:

| Período | Modelo | Arquivo | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- | --- | --- |
| 2010–2025 | floresta, 300 árvores | 68,8 MB | 0,499 | 48,7% |
| 2010–2025 | floresta, 100 árvores | 22,8 MB | 0,499 | 48,9% |
| 2015–2025 | floresta, 100 árvores | 15,6 MB | 0,476 | 43,4% |
| 2018–2025 | floresta, 100 árvores | 10,4 MB | 0,455 | 36,2% |
| **2010–2025** | **boosting** *(atual)* | **1,3 MB** | **0,564** | **57,4%** |

> As quatro primeiras linhas vêm da medição de agosto/2026, feita para decidir
> o corte de anos; comparam-se entre si. A última é do modelo atual, medido
> depois de a base ganhar as variáveis de clima — o salto de 0,499 para 0,564
> não é só efeito do algoritmo.

A troca pelo boosting resolveu o problema do tamanho por outro caminho: o
arquivo ficou 17× menor que a floresta de 100 árvores, com a base inteira e
acurácia maior. Cortar anos continua sendo má ideia — até 2018 derrubaria a
detecção de casos graves de 49% para 36%.

Se ainda assim quiser um dataset menor (para treinar mais rápido, por exemplo):

```bash
python dados/preparar_dados.py --anos 2015 2025
```

> Detalhe importante: cortar o **período do dataset** não apaga o histórico. As
> variáveis de cada linha continuam usando todas as ocorrências desde 1991 —
> o corte só reduz quantos meses viram exemplo de treino.

---

## Testes

```bash
pytest
```

258 testes cobrindo o ETL, o contrato de dados, o vazamento temporal, o
modelo, a API, o histórico por ano, a camada de chuva, as capitais e a
interface.

---

## Limitações (para responder à banca)

- **Sem gatilho climático de verdade.** A chuva do INMET foi incorporada e
  medida — e não melhorou a previsão (a seção acima explica por quê). O modelo
  sabe que Petrópolis é perigosa em fevereiro; não sabe se vai chover **neste**
  fevereiro, porque isso é meteorologia e não histórico.
- **O futuro é sempre o mesmo futuro.** A base termina em dezembro de 2025.
  De 2026 em diante o modelo responde com o histórico congelado nessa data, e
  por isso o mesmo mês de anos diferentes recebe a mesma resposta.
- **Subnotificação.** Município que não registra ocorrência aparece como sem
  risco.
- **Probabilidade relativa, não absoluta.** Os meses sem desastre foram
  amostrados; use para comparar e priorizar municípios.
- **O rótulo é uma construção do trabalho**, derivada dos danos declarados.

---

## Próximos passos

- [x] ~~Incorporar chuva e temperatura do INMET/CEMADEN~~ — feito, e medido:
      explica o desastre, mas não melhora a previsão mensal
- [x] ~~Adicionar coordenadas do IBGE para ativar o mapa~~ — feito: mapa do país
      inteiro, desenhado em SVG puro, sem biblioteca externa
- [ ] Atualizar a base do Atlas quando 2026 entrar, e mover a janela de
      previsão junto
- [ ] Prever por semana ou por dia, e não por mês — é a mudança que faria a
      chuva finalmente ajudar
- [ ] Melhorar a detecção da classe `medio`

---

## Fluxo de trabalho no Git

```bash
git pull origin main
```

Depois de alterar o código:

```bash
pytest
git status
git add .
git commit -m "Mensagem descrevendo a alteração"
git push origin main
```
