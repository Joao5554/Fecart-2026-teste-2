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

**4. Baixar a base do Atlas**

Baixe a base consolidada em <https://atlasdigital.mi.gov.br> (arquivo
`BD_Atlas_..._Consolidado.csv`) e salve em `dados/bruto/`.

**5. Preparar o dataset**

```bash
python dados/preparar_dados.py
```

**6. Treinar o modelo**

```bash
python treinamento/treinar_modelo.py
```

**7. Subir o sistema**

```bash
uvicorn backend.app:app --reload
```

- Interface: **http://127.0.0.1:8000/app**
- Documentação da API: **http://127.0.0.1:8000/docs**

---

## Estrutura do projeto

| Pasta / arquivo                    | O que é                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| `src/esquema.py`                   | **Contrato de dados** — quais colunas, unidades e faixas        |
| `src/atlas.py`                     | Converte o Atlas bruto no dataset e calcula as features         |
| `src/carregar.py`                  | Lê o CSV e valida contra o contrato antes de treinar            |
| `src/caracteristicas.py`           | Features derivadas e pré-processamento (imputação + one-hot)    |
| `src/procedencia.py`               | Registra se o dataset veio da base real ou de dados sintéticos  |
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
| Acurácia | 68,1% |
| Acurácia balanceada | 49,9% |
| F1 macro | 0,507 |
| Casos de risco **alto** identificados | **48,7%** |

| Classe | Precisão | Recall | F1 |
| --- | --- | --- | --- |
| baixo | 0,748 | 0,841 | 0,792 |
| medio | 0,495 | 0,168 | 0,251 |
| alto  | 0,472 | 0,487 | 0,479 |

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

A pasta inteira passa de 500 MB, mas quase tudo é descartável na hora de
apresentar. Para **rodar** o sistema bastam o código, o modelo treinado e o
histórico que a API consulta:

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
