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

Medidos em **divisão temporal**: o modelo treina com 2010–2021 e é avaliado em
2022–2025, que ele nunca viu. É assim que o sistema seria usado de verdade.

| Métrica | Valor |
| --- | --- |
| Acurácia | 71,8% |
| Acurácia balanceada | 55,3% |
| F1 macro | 0,565 |
| Casos de risco **alto** identificados | **56,2%** |

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
- **Divisão temporal.** Treina no passado, testa no futuro. A validação cruzada
  aleatória também é calculada, e o próprio treino avisa que ela é otimista.
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
| `POST` | `/mapa/risco` | GeoJSON pronto para um mapa interativo |

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
- [ ] Adicionar coordenadas do IBGE para ativar o mapa (`/mapa/risco` já existe)
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
