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

Pronto. **O modelo treinado vem junto no repositório** (23 MB), assim como o
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
| `dados/README.md`                  | **Metodologia dos dados** e limitações — leitura obrigatória    |
| `treinamento/treinar_modelo.py`    | Treina, avalia e salva o modelo                                 |
| `backend/app.py`                   | API que serve as previsões                                      |
| `frontend/`                        | Interface web (HTML/CSS/JS puro, sem bibliotecas)               |
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
| Acurácia | 71,3% |
| Acurácia balanceada | 55,3% |
| F1 macro | 0,561 |
| Casos de risco **alto** identificados | **57,8%** |

### Validação walk-forward: o desempenho é estável?

Uma única divisão pode dar sorte. A validação por **janela expansiva** treina
até um ano e testa no seguinte, repetidamente — como o sistema seria usado:

| Treina até | Testa | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- | --- |
| 2017 | 2018 | 59,4% | 74,8% |
| 2018 | 2019 | 64,5% | 80,5% |
| 2019 | **2020** | **46,3%** | **34,7%** |
| 2020 | 2021 | 54,9% | 59,8% |
| 2021 | 2022 | 59,0% | 64,5% |
| 2022 | 2023 | 55,8% | 56,7% |
| 2023 | 2024 | 50,6% | 50,0% |
| 2024 | 2025 | 59,3% | 73,1% |
| | **média** | **56,2% ± 5,7** | **61,8% ± 14,9** |

**2020 é o pior ano de todos**, e por uma margem grande. O modelo treinado até
2019 não anteciparia o que aconteceu ali: a taxa de ocorrências registradas
salta de 20% (2019) para 29% (2020) e continua subindo. Parte é aumento real
de eventos, parte é melhora da notificação — e nenhum modelo baseado em
histórico prevê uma mudança na forma de registrar.

Esse é o resultado mais honesto do trabalho: o desempenho **varia com o ano**,
e apresentar só a média esconderia isso.

### Escolha dos hiperparâmetros pela parcimônia

Entre os candidatos testados na validação, o de maior F1 foi profundidade 28
(0,517), mas o escolhido foi profundidade 16 (0,508). É intencional: a
diferença de 0,009 cabe dentro da tolerância de 0,01 e é ruído de amostra.
**Entre modelos empatados, vence o mais simples** — generaliza melhor para
dados que ainda não existem, e gera um arquivo menor (19 MB em vez de 31 MB).

**Como ler isso com honestidade.** A acurácia de 68% não é o número importante:
como 75% das linhas são "baixo", chutar sempre "baixo" já daria mais que isso.
O número que importa num sistema de alerta é quantos casos graves o modelo
**pega** — 48,7% — e ele foi obtido pesando o erro: deixar de avisar um risco
alto custa mais caro que um alarme falso. Com pesos neutros, o modelo acertava
mais no total e detectava bem menos casos graves.

A classe `medio` é a mais difícil (recall 0,168), o que faz sentido: ela é
justamente a faixa ambígua entre "nada aconteceu" e "aconteceu algo grave".

O modelo aprendeu padrões coerentes com a realidade — a variável mais
importante é a atividade recente do mesmo tipo de desastre na UF, seguida do
tempo desde a última ocorrência no município e da sazonalidade do mês.

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
muda divisão nenhuma — o Random Forest é indiferente à escala. Padronizar é
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

A importância que o Random Forest devolve diz **quanto** uma variável ajudou a
separar os casos — mas não diz a **direção** nem o **tamanho** do efeito. Para
isso o projeto ajusta também uma **regressão logística** sobre os mesmos dados
e reporta a razão de chances:

    OR = 2,0  ->  a chance dobra
    OR = 1,0  ->  a variável não altera a chance
    OR = 0,5  ->  a chance cai pela metade

São dois modelos com papéis diferentes, de propósito: a floresta **prevê** (é o
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
| `GET` | `/mapa/brasil` | Risco de todos os municípios de uma vez — é o que pinta o mapa |
| `POST` | `/mapa/risco` | GeoJSON de pontos, para quem já tem coordenadas |

O endpoint que a interface usa é o `/prever/municipio`: quem consulta informa
apenas **onde, o quê e quando**, e o backend calcula as quinze variáveis
históricas a partir do Atlas.

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

Gera a pasta `apresentacao/` com **28 MB** — cabe em qualquer pendrive. Dentro
dela vai um `LEIAME.md` com o passo a passo para quem for rodar.

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
qualidade, enquanto o número de árvores da floresta afeta o tamanho:

| Período | Árvores | Modelo | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- | --- | --- |
| 2010–2025 | 300 | 68,8 MB | 0,499 | 48,7% |
| **2010–2025** | **100** | **22,8 MB** | **0,499** | **48,9%** |
| 2015–2025 | 100 | 15,6 MB | 0,476 | 43,4% |
| 2018–2025 | 100 | 10,4 MB | 0,455 | 36,2% |

Reduzir de 300 para 100 árvores deixa o modelo **3× menor sem custo nenhum** —
por isso 100 é o padrão. Já cortar até 2018 economizaria só mais 12 MB e
derrubaria a detecção de casos graves de 49% para 36%.

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

71 testes cobrindo o ETL, o contrato de dados, o vazamento temporal, o modelo,
a API e a interface. **Rode antes de todo commit.**

---

## Limitações (para responder à banca)

- **Sem gatilho climático.** O Atlas não traz chuva nem temperatura. O modelo
  sabe que Petrópolis é perigosa em fevereiro, mas não sabe se vai chover neste
  fevereiro. Incorporar o INMET é o próximo passo natural.
- **Subnotificação.** Município que não registra ocorrência aparece como sem
  risco.
- **Probabilidade relativa, não absoluta.** Os meses sem desastre foram
  amostrados; use para comparar e priorizar municípios.
- **O rótulo é uma construção do trabalho**, derivada dos danos declarados.

---

## Próximos passos

- [ ] Incorporar chuva e temperatura do INMET/CEMADEN
- [x] ~~Adicionar coordenadas do IBGE para ativar o mapa~~ — feito: mapa do país
      inteiro, desenhado em SVG puro, sem biblioteca externa
- [ ] Testar divisão temporal mais longa (treinar até 2019, testar 2020–2025)
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
