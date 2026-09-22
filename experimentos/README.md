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

### A recomendação

As duas estratégias respondem a perguntas diferentes, e as duas têm uso:

| Para... | Usar | Por quê |
| --- | --- | --- |
| **Relatar o desempenho** | temporal | É a única que reproduz o uso real: em 2026 só existe o passado. Reportar 65% seria prometer o que o sistema não entrega. |
| **Comparar modelos** | aleatória ou blocos | Desvio de ±0,4% contra ±4,9%. Com ruído tão menor, ela distingue duas variantes que a temporal não consegue separar. |

Ou seja: o professor está certo sobre a **estabilidade** da estimativa
aleatória, e ela passa a ser usada para escolher entre modelos. Mas o número
que vai para a apresentação continua sendo o temporal, porque é o honesto.

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

### O achado mais útil: as probabilidades estão mal calibradas

A interface mostra "72% de chance de ser grave". Medimos se isso corresponde
à realidade:

| O modelo dizia | Aconteceu de fato | Desvio |
| --- | --- | --- |
| 0%–20% | 5,1% | −7,6% |
| 20%–40% | 16,6% | −11,1% |
| 40%–60% | 40,7% | −7,0% |
| 60%–80% | 59,4% | −11,4% |
| 80%–100% | 76,8% | −6,9% |

O modelo é **sistematicamente otimista**: promete mais risco do que acontece,
em todas as faixas. Erro de Brier 0,128.

Isso não afeta a ordenação dos municípios — o mapa continua certo sobre quem é
mais perigoso que quem. Mas afeta o número exibido. **Aplicar calibração
(isotônica ou Platt) na validação corrigiria isso sem mexer na acurácia**, e é
a única mudança destes experimentos que eu recomendaria levar para produção.

---

## O que NÃO foi alterado

Nenhum destes experimentos tocou em `modelo/`, `src/esquema.py`, no pipeline
de treino ou na API. O modelo em produção continua exatamente como estava.
Qualquer mudança sugerida aqui precisa ser decidida e aplicada à parte.
