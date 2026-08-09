# Fecart 2026 — Previsão de Risco de Desastres Naturais

Sistema que estima o **nível de risco** (baixo, médio ou alto) de desastres
naturais por município brasileiro, a partir do histórico de ocorrências do
**S2iD** (Defesa Civil) combinado com dados climáticos e territoriais.

A previsão é servida por uma API, no formato que um mapa interativo do Brasil
consome diretamente.

> **Estado atual:** o pipeline está completo e testado, rodando sobre dados
> **sintéticos**. A base real ainda não foi incorporada. Os números de acurácia
> abaixo servem para verificar o encanamento, não como resultado do projeto.

## Como rodar (primeira vez)

```bash
python -m venv .venv
```

Ative o ambiente virtual (Windows/PowerShell):

```powershell
.venv\Scripts\activate
```

> Se aparecer erro de "execução de scripts foi desabilitada", rode uma vez
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` e abra
> um novo terminal.

Instale as bibliotecas:

```bash
pip install -r requirements.txt
```

Gere os dados de teste (enquanto a base real não chega):

```bash
python dados/gerar_dados_sinteticos.py
```

Treine o modelo:

```bash
python treinamento/treinar_modelo.py
```

Suba a API:

```bash
uvicorn backend.app:app --reload
```

Abra <http://127.0.0.1:8000/docs> para testar tudo pelo navegador.

## Estrutura do projeto

| Pasta / arquivo                    | O que é                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| `src/esquema.py`                   | **Contrato de dados** — quais colunas, unidades e faixas        |
| `src/carregar.py`                  | Lê o CSV e valida contra o contrato antes de treinar            |
| `src/caracteristicas.py`           | Features derivadas e pré-processamento (imputação + one-hot)    |
| `src/procedencia.py`               | Registra se o CSV usado é sintético ou real                     |
| `dados/gerar_dados_sinteticos.py`  | Gera CSV de teste no formato exato do contrato                  |
| `dados/README.md`                  | **Onde baixar os dados reais** e como montar o rótulo           |
| `treinamento/treinar_modelo.py`    | Treina, avalia e salva o modelo                                 |
| `backend/app.py`                   | API que serve as previsões                                      |
| `backend/esquemas_api.py`          | Formato de entrada e saída da API                               |
| `testes/`                          | Testes automatizados (`pytest testes/`)                         |
| `modelo/`                          | Saída do treino: `modelo.pkl` e `metadados.json`                |

`src/esquema.py` é a peça central: treino e API leem dele, então nunca há
divergência entre o que o modelo aprendeu e o que a API aceita. Para ver o
contrato inteiro:

```bash
python -m src.esquema
```

## Como o projeto se protege de erro silencioso

Três cuidados que só aparecem quando algo dá errado — e que evitam o pior
cenário de um trabalho como este, que é apresentar um número inválido sem
ninguém perceber:

- **Procedência dos dados.** O gerador marca o CSV sintético com um hash. O
  treino grava a origem no `metadados.json` e avisa em destaque; a API repete
  o aviso em `GET /` e `GET /modelo/info`. Trocar o CSV pela base real
  invalida a marca automaticamente (detalhes em [`dados/README.md`](dados/README.md)).
- **Assinatura do esquema.** Cada modelo guarda uma impressão digital do
  contrato de dados com que foi treinado. Se alguém mudar as colunas em
  `src/esquema.py` e esquecer de retreinar, a API **recusa** o modelo antigo
  e diz o que fazer, em vez de responder com previsões sem sentido.
- **Pipeline salvo inteiro.** As transformações vão dentro do `.pkl`, então a
  API aplica exatamente o mesmo tratamento usado no treino.

## Como o problema foi modelado

Uma linha do dataset = **um município, em um mês, para um tipo de desastre**.
O tipo de desastre (COBRADE) entra como variável de entrada, o que permite um
único modelo cobrir inundação, deslizamento, seca, vendaval e os demais — em
vez de manter nove modelos separados.

- **Entrada:** 38 variáveis — território (declividade, população, área de
  risco), clima do período (chuva, umidade, temperatura, vento) e histórico do
  S2iD (ocorrências, decretos, danos).
- **Saída:** `baixo`, `medio` ou `alto`, com a probabilidade de cada nível.
- **Algoritmo:** Random Forest dentro de um `Pipeline` do scikit-learn, que
  inclui o pré-processamento. O pipeline inteiro é salvo, então a API aplica
  exatamente as mesmas transformações do treino.

Três decisões que valem menção na apresentação:

1. **`class_weight="balanced"`** — risco alto é ~12% dos casos. Sem isso o
   modelo aprende a chutar "baixo" sempre e exibe uma acurácia alta e inútil.
2. **Acurácia balanceada como métrica principal** — a acurácia simples engana
   quando as classes são desbalanceadas.
3. **Recall da classe "alto"** é o número que mais importa. Num sistema de
   alerta, deixar de avisar um risco real custa muito mais caro que um alarme
   falso — e o treino imprime esse número em destaque.

## Treinar o modelo

```bash
python treinamento/treinar_modelo.py
```

Opções úteis:

```bash
python treinamento/treinar_modelo.py --sem-validacao-cruzada
```

| Opção                     | Para que serve                                  |
| ------------------------- | ----------------------------------------------- |
| `--dados CAMINHO`         | usar outro CSV                                  |
| `--arvores N`             | número de árvores (padrão: 300)                 |
| `--profundidade N`        | limitar a profundidade das árvores              |
| `--proporcao-teste 0.2`   | fração reservada para teste                     |
| `--sem-validacao-cruzada` | pula a validação cruzada (bem mais rápido)      |

O script valida os dados, treina, avalia e salva `modelo/modelo.pkl` junto de
`modelo/metadados.json` — que registra métricas, período coberto, versões das
bibliotecas e importância das variáveis daquele treino.

## A API

| Método | Rota                 | O que faz                                        |
| ------ | -------------------- | ------------------------------------------------ |
| GET    | `/`                  | estado da API e do modelo                        |
| GET    | `/esquema`           | contrato de dados (quais campos enviar)          |
| GET    | `/modelo/info`       | métricas e metadados do modelo carregado         |
| POST   | `/modelo/recarregar` | recarrega o `.pkl` sem reiniciar o servidor      |
| POST   | `/prever`            | previsão para um município                       |
| POST   | `/prever/lote`       | previsão para vários municípios de uma vez       |
| POST   | `/mapa/risco`        | **GeoJSON pronto para o mapa interativo**        |

`/mapa/risco` devolve o formato padrão que Leaflet, Mapbox e OpenLayers
consomem direto. Cada ponto já vem com `properties.cor` e
`properties.nivel_risco`, então o frontend só precisa jogar o resultado numa
camada do mapa.

Para pintar o país inteiro, use `/mapa/risco` ou `/prever/lote` com todos os
municípios de uma vez — uma chamada com N linhas é muito mais rápida que N
chamadas.

## Testes

```bash
pytest testes/ -v
```

Cobrem o contrato de dados, as features derivadas, a validação, o pipeline de
treino e todos os endpoints da API. Os testes da API são pulados
automaticamente se ainda não houver modelo treinado.

## Próximos passos

1. **Incorporar a base real do S2iD** — ver [`dados/README.md`](dados/README.md),
   que lista as fontes e explica como construir o rótulo `nivel_risco`.
2. **Trocar a divisão treino/teste por uma divisão temporal** (treinar até
   2022, testar em 2023–2024). Com dados reais e série temporal, o split
   aleatório superestima o desempenho.
3. **Conferir vazamento temporal** — as features de um mês têm que prever o mês
   seguinte, nunca o próprio.
4. **Construir o mapa interativo** consumindo `/mapa/risco`.

## Fluxo de trabalho no git

Antes de começar a programar:

```bash
git pull origin main
```

Depois de alterar o código:

```bash
git add . ; git commit -m "Mensagem descrevendo a alteração" ; git push origin main
```

Se instalar uma biblioteca nova, atualize o `requirements.txt`:

```bash
pip freeze > requirements.txt
```
