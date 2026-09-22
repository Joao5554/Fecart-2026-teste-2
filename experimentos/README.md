# Experimentos

Pasta isolada. **Nada aqui altera o modelo em produção**: os scripts só leem
`dados/dados.csv` e gravam relatórios em `experimentos/resultados/`. Podem ser
rodados, refeitos ou apagados sem consequência para o sistema.

```bash
python experimentos/comparar_validacao.py       # aleatória vs blocos vs temporal
python experimentos/diagnosticar_diferenca.py   # de onde vem a diferença
python experimentos/melhorar_modelo.py          # tentativas de ganhar acurácia
```

---

## 1. A validação deveria ser aleatória?

A dúvida levantada: dividir por período sequencial poderia enganar a acurácia,
e o correto seria sortear as linhas. Fomos medir.

### Quatro estratégias, mesmo modelo, mesmos dados

| Estratégia | Acurácia balanceada | Risco alto detectado |
| --- | --- | --- |
| Aleatória (K-fold estratificado) | **65,1% ± 0,4** | 80,7% |
| Blocos por município | 64,9% ± 0,3 | 80,7% |
| Blocos por estado | 54,6% ± 3,7 | 64,3% |
| Temporal (janela expansiva) | 56,2% ± 4,9 | 63,6% |

### O que isso mostra

**A objeção mais comum à validação aleatória não se aplica aqui.** O medo
seria o modelo decorar quais municípios são perigosos, já que a mesma cidade
aparece dos dois lados. Bloquear por município derruba isso em apenas
0,2 ponto — e um teste direto confirma: avaliando em cidades que o modelo
**nunca viu**, a queda é de 0,5 ponto. O modelo aprendeu o mecanismo, não a
lista de cidades.

**Mas a diferença para a validação temporal é real: 8,9 pontos.**

### De onde vem essa diferença

A primeira hipótese testada — que a base muda ao longo dos anos — deu um
resultado confuso, porque a comparação era injusta: a validação temporal
treina com menos linhas, e parte da queda vinha daí, não da ordem do tempo.

O teste corrigido fixa **o mesmo ano de teste e o mesmo número de linhas de
treino**, mudando só de onde elas vêm:

| Ano testado | Linhas de treino | Só passado | Sorteado (vê o futuro) | Diferença |
| --- | --- | --- | --- | --- |
| 2018 | 88.859 | 58,6% | 61,1% | +2,6% |
| 2020 | 111.098 | 47,8% | 52,6% | +4,7% |
| 2022 | 135.219 | 57,7% | 59,9% | +2,2% |
| 2024 | 161.733 | 52,7% | 53,4% | +0,6% |
| | | | **média** | **+2,5%** |

Conclusão: **poder ver anos posteriores vale 2,5 pontos** — vantagem que não
existe na vida real. Os outros ~6 pontos da diferença vêm de a validação
aleatória tirar média de todos os anos, inclusive os fáceis, enquanto a janela
expansiva testa ano a ano, cada um com menos histórico.

### A recomendação (corrigida por medição)

A primeira versão deste documento recomendava usar a validação aleatória para
**escolher** modelos, argumentando que o ruído dez vezes menor (±0,4% contra
±4,9%) permitiria distinguir configurações que a temporal confunde.

**Fomos medir, e estava errado.** Ver `quantificar_ganhos.py`:

| Configuração | F1 na CV aleatória | F1 na val. temporal |
| --- | --- | --- |
| prof. 10, folha 20 | 0,553 | 0,503 |
| prof. 16, folha 5 | 0,623 | 0,513 |
| prof. 26, folha 3 | 0,657 | **0,514** |
| **sem limite, folha 2** | **0,665** | 0,514 |

A CV aleatória sobe monotonicamente com a complexidade e escolhe a árvore sem
limite de profundidade. Faz sentido: quanto mais o modelo decora, melhor ele
vai num teste que contém meses vizinhos do treino. A validação temporal fica
praticamente plana — ela não vê vantagem em decorar, porque o teste é um ano
que ninguém viu.

No teste comum (2022–2025):

| Critério de escolha | Balanceada | F1 macro | Risco alto |
| --- | --- | --- | --- |
| Escolha da CV aleatória | 52,6% | 0,550 | 46,8% |
| **Escolha da val. temporal** | **53,6%** | **0,557** | **50,4%** |

**Escolher pela CV aleatória custa 1,1 ponto.** Ela não só superestima o
resultado — ela seleciona o modelo errado, porque premia exatamente a
memorização que não se transfere para o ano seguinte.

É o que Roberts et al. (2017) chamam de "ampla oportunidade de sobreajuste
com preditores não causais": a validação aleatória não erra só a nota, erra a
escolha.

| Para... | Usar | Por quê |
| --- | --- | --- |
| **Relatar o desempenho** | temporal | Única que reproduz o uso real |
| **Escolher modelos** | temporal | Medido: a aleatória escolhe 1,1 ponto pior |

A estabilidade da estimativa aleatória é real, mas não compensa: uma medida
precisa da coisa errada continua sendo a coisa errada.

Blocos por **estado** (54,6%) ficam próximos da temporal e revelam outra
fragilidade: o modelo generaliza mal para um estado inteiro que não viu.

### Referências

- Roberts et al. (2017). *Cross-validation strategies for data with temporal,
  spatial, hierarchical, or phylogenetic structure*. **Ecography** 40:913–929.
  [doi:10.1111/ecog.02881](https://doi.org/10.1111/ecog.02881) — validação
  aleatória subestima o erro quando há estrutura de dependência; recomendam
  validação em blocos.
- Bergmeir, Hyndman & Koo (2018). *A note on the validity of cross-validation
  for evaluating autoregressive time series prediction*. **Computational
  Statistics & Data Analysis** 120:70–83.
  [doi:10.1016/j.csda.2017.11.003](https://doi.org/10.1016/j.csda.2017.11.003)
  — K-fold é válido em séries temporais **se** o modelo for puramente
  autorregressivo e os erros não forem correlacionados.
- Cawley & Talbot (2010). *On over-fitting in model selection and subsequent
  selection bias in performance evaluation*. **JMLR** 11:2079–2107 —
  escolher hiperparâmetro na mesma partição que reporta o desempenho gera
  viés otimista; a correção é validação aninhada.

---

## 2. Dá para melhorar a acurácia?

Quatro ideias, todas escolhidas na **validação** (2020–2021) e medidas uma
única vez no **teste** (2022–2025).

| Variante | Balanceada | F1 macro | Risco alto |
| --- | --- | --- | --- |
| Random Forest multiclasse *(atual)* | 51,7% | 0,529 | 50,5% |
| Gradient boosting | 51,7% | 0,533 | 45,8% |
| Hierárquico (ocorrência × gravidade) | 48,8% | 0,501 | 43,1% |
| Hierárquico com peso maior no grave | 51,0% | 0,487 | **63,3%** |
| Gradient boosting + limiar ajustado | **52,3%** | 0,532 | 50,8% |

### Leitura honesta

**Nenhuma ideia trouxe ganho relevante.** O melhor resultado, gradient
boosting com limiar ajustado, soma 0,7 ponto — dentro da variação entre anos
(desvio de 4,9 pontos na validação temporal). Não é um ganho em que dá para
confiar.

A decomposição hierárquica era a aposta mais promissora, porque espelha como
o rótulo foi construído (primeiro "houve?", depois "foi grave?"). Ela piorou.
Explicação provável: o segundo modelo treina só nas ~25% de linhas com
ocorrência, e perde mais em dados do que ganha em foco.

**A variante hierárquica com peso alto merece nota:** troca 0,7 ponto de
acurácia balanceada por **+12,8 pontos de detecção de casos graves** (63,3%
contra 50,5%). Para um sistema de alerta, essa troca pode valer a pena — é
uma decisão de projeto, não de estatística.

### A calibração: também medida, e também não compensa

A versão anterior deste documento recomendava calibrar as probabilidades,
porque o modelo parecia otimista faixa a faixa. Medindo direito:

| Versão | Brier | Erro de calibração | Balanceada | Risco alto |
| --- | --- | --- | --- | --- |
| **Sem calibração** | **0,1185** | **5,4%** | **53,6%** | **50,4%** |
| Isotônica | 0,1312 | 11,1% | 50,2% | 34,0% |
| Sigmoide (Platt) | 0,1332 | 11,7% | 49,3% | 33,1% |

**Calibrar piorou tudo.** O erro de calibração dobrou, e a acurácia caiu 3,5
pontos.

Dois enganos meus, corrigidos aqui:

1. **O desvio era menor do que parecia.** Eu havia citado desvios de −7% a
   −11% por faixa. O erro de calibração esperado, que pondera as faixas pelo
   número de casos, é **5,4%** — o modelo já era razoavelmente calibrado.

2. **A correção não atravessa o tempo.** A calibração foi ajustada em
   2020–2021 e aplicada em 2022–2025. Como a taxa de ocorrências muda entre
   os períodos (de 28% para 34%), a correção aprendida é a errada: o modelo
   calibrado passa a prever 9,2% de risco alto onde acontecem 19,0%.

É a mesma deriva que explica a diferença entre validação aleatória e temporal,
aparecendo de outra forma. **Calibrar num período e usar em outro não
funciona nesta base.**

---

## Resposta curta: quanto cada mudança rende, em porcentagem

| Mudança | Efeito na acurácia balanceada |
| --- | --- |
| Gradient boosting | +0,0% |
| Gradient boosting + limiar ajustado | +0,7% *(dentro do ruído de ±4,9%)* |
| Escolher hiperparâmetros pela CV aleatória | **−1,1%** |
| Decomposição hierárquica | −2,9% |
| Calibração isotônica | **−3,5%** |

**Nenhuma ajuda.** As duas que eu havia recomendado — CV aleatória para
escolha e calibração — são as duas piores. A única com sinal positivo soma
0,7 ponto, sete vezes menor que a variação entre anos.

Vale registrar a exceção: a decomposição hierárquica com peso alto no evento
grave perde 0,7 ponto de acurácia mas ganha **+12,8 pontos na detecção de
casos graves** (63,3% contra 50,5%). Para um sistema de alerta essa troca
pode valer — é decisão de projeto, não de estatística.

### Por que quase nada funciona

Os três resultados apontam para a mesma causa. A base **muda de comportamento
ao longo dos anos**: a taxa de ocorrências registradas sobe de 19% (2010) para
34% (2023), por aumento real de eventos e por melhora da notificação.

Qualquer ajuste fino aprendido num período — hiperparâmetro, calibração,
limiar — chega ao período seguinte desatualizado. O ganho real não virá de
afinar o modelo, e sim de dado novo que explique o evento (chuva em resolução
diária, e não mensal) ou de mudar a resolução do alvo.

---

## O que NÃO foi alterado

Nenhum destes experimentos tocou em `modelo/`, `src/esquema.py`, no pipeline
de treino ou na API. O modelo em produção continua exatamente como estava.
Qualquer mudança sugerida aqui precisa ser decidida e aplicada à parte.
