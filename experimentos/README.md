# Experimentos

Pasta isolada. Os scripts só leem `dados/dados.csv` e gravam relatórios em
`experimentos/resultados/` — rodar qualquer um deles não mexe no modelo em
produção.

```bash
python experimentos/comparar_validacao.py       # aleatória vs blocos vs temporal
python experimentos/diagnosticar_diferenca.py   # de onde vem a diferença
python experimentos/melhorar_modelo.py          # tentativas de ganhar acurácia
python experimentos/validar_ganho.py            # o ganho se repete em outros anos?
python experimentos/horizonte_previsao.py       # até onde no futuro dá para prever
python experimentos/testar_geografia.py         # altitude e rio ajudam?
python experimentos/confiabilidade.py           # a porcentagem mostrada é confiável?
```

> **Duas coisas medidas aqui foram aplicadas ao projeto.** A seção 3 aprovou a
> troca do Random Forest pelo gradient boosting; a seção 4 encontrou um defeito
> real na previsão de meses futuros e a correção está em `src/atlas._ancora`.
> As demais continuam apenas medidas e documentadas.

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
| Random Forest multiclasse *(o modelo de então)* | 51,7% | 0,529 | 50,5% |
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

## 3. O +0,7% era real? Seis anos dizem que era outra coisa

A seção 2 encontrou um único candidato com sinal positivo — gradient boosting
**com limiar ajustado**, +0,7 ponto — e avisou que o número cabia dentro do
ruído. Uma medição só não decide isso. `validar_ganho.py` repete a comparação
em **seis anos independentes**:

    para cada ano Y de 2019 a 2024:
        treina  com tudo até Y-2
        valida  em Y-1      -> o limiar é escolhido aqui
        testa   em Y

A regra de aprovação foi escrita **antes** de rodar: vencer em pelo menos 4
dos 6 anos e ter média positiva. Fixar o critério antes é o que impede a
armadilha descrita por Cawley & Talbot (2010) — olhar o resultado e só então
decidir o que conta como sucesso.

### O resultado

| Variante | Balanceada (média) | F1 macro | Risco alto | Diferença | Anos vencidos |
| --- | --- | --- | --- | --- | --- |
| Random Forest *(o modelo de então)* | 53,9% | 0,548 | 54,8% | — | — |
| **Gradient boosting** | **54,9%** | 0,552 | 54,1% | **+1,04%** | **5 de 6** |
| Floresta + limiar | 53,1% | 0,549 | 48,6% | −0,82% | 1 de 6 |
| Boosting + limiar | 53,9% | **0,554** | 46,2% | +0,06% | 3 de 6 |

Ano a ano, a diferença do boosting para a floresta:

| 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
| --- | --- | --- | --- | --- | --- |
| +1,8% | −0,9% | +2,3% | +1,6% | +1,2% | +0,4% |

### O que isso corrige na seção 2

**O ganho não vinha do limiar — vinha do boosting, e o limiar atrapalhava.**
A seção 2 testou os dois juntos, numa única partição, e não separou um do
outro. Medidos em separado, em seis anos:

- boosting sozinho: **+1,04 ponto**, melhor em 5 dos 6 anos;
- boosting + limiar: +0,06 ponto — o limiar devolve quase todo o ganho;
- floresta + limiar: −0,82 ponto, pior em 5 dos 6 anos.

O motivo é o mesmo que derrubou a calibração: o limiar é escolhido num ano e
aplicado no seguinte, e a taxa de ocorrências não para quieta entre um ano e
outro. Qualquer ajuste fino aprendido num período chega desatualizado ao
período seguinte.

Também vale notar o que o limiar faz com a detecção de casos graves: ele a
derruba de 54,8% para 48,6% (floresta) e 46,2% (boosting). Maximizar F1 macro
na validação levou o limiar para cima, e um limiar alto é conservador demais
para um sistema de alerta.

### Quão forte é essa evidência?

| Teste | Resultado | Leitura |
| --- | --- | --- |
| Média das diferenças | +1,04 ponto | ganho pequeno |
| Teste t pareado, unilateral | t = 2,23, gl = 5, **p = 0,038** | significativo a 5% |
| Teste t pareado, bilateral | p = 0,076 | no limite |
| Teste dos sinais | 5 de 6, p = 0,11 | não significativo |

O teste é **pareado** de propósito: cada ano é avaliado pelos dois modelos nas
mesmas linhas, e a pergunta é se a *diferença* entre eles é consistentemente
positiva. Comparar as duas médias soltas afogaria o sinal na variação entre
anos, que é de ±5 pontos — quarenta vezes maior que o efeito procurado.

Sendo honesto: **é evidência fraca, porém consistente.** Seis anos são poucos,
e o teste que não supõe normalidade (o dos sinais) não alcança significância.
O que sustenta a decisão é a regularidade — cinco dos seis anos, sempre entre
+0,4 e +2,3 pontos, e o único ano negativo é 2020, justamente o ano em que
todos os modelos desabam.

### O que mudou no projeto

Esta é a única mudança medida nesta pasta que **foi aplicada**. O modelo em
produção passou a ser o gradient boosting em 25/09/2026, treinado na mesma
base (`sha256 64f79fb6…`, 187.088 linhas) e com o mesmo protocolo de sempre:

| Medida | Floresta (antes) | **Boosting (agora)** |
| --- | --- | --- |
| Acurácia | 72,8% | 70,2% |
| **Acurácia balanceada** | 55,0% | **56,4%** |
| F1 macro | 0,564 | **0,568** |
| Risco alto detectado | 56,1% | **57,4%** |
| Walk-forward (8 anos) — média | 56,3% | **58,1%** |
| Walk-forward — desvio entre anos | 4,9% | 5,8% |
| Tamanho do `modelo.pkl` | 33,6 MB | **1,3 MB** |

Três observações honestas sobre esta tabela:

1. **A acurácia bruta caiu 2,6 pontos, e está tudo certo.** Três em cada
   quatro linhas são "baixo": um modelo que chuta "baixo" sempre acerta 75%.
   A acurácia balanceada, que tira a média do acerto por classe, é a medida
   que o projeto relata — e ela subiu.
2. **O desvio entre anos subiu** (4,9% → 5,8%). O boosting é um pouco menos
   estável. O pior ano dos dois é praticamente o mesmo (47,4% contra 46,9%).
3. **O arquivo ficou 26× menor**, o que não era o objetivo, mas resolve de
   vez o problema de levar o projeto para o computador da escola.

A floresta não foi apagada: `--modelo floresta` reproduz o modelo anterior,
e é assim que a comparação pode ser refeita a qualquer momento.

---

## 4. Até onde no futuro a previsão ainda significa alguma coisa

Este não começou como experimento. Começou como uma pergunta de interface — a
apresentação é em setembro de 2026, então os meses oferecidos passaram a ser
de **09/2026 a 12/2027** — e virou o defeito mais sério encontrado até agora.

### O defeito

Quatro das variáveis mais importantes contam o que aconteceu nos 12, 24 e 60
meses **anteriores** ao mês pedido. A base termina em dezembro de 2025. Ao
pedir um mês de 2027, a janela de 12 meses cai inteira num período sem
registro, e as contagens viram zero — não porque nada aconteceu, mas porque o
Atlas ainda não chegou lá.

`horizonte_previsao.py` mede o estrago nos 18.980 pares (município, tipo):

| Mês pedido | 09/2026 | 12/2026 | 01/2027 | 06/2027 | 12/2027 |
| --- | --- | --- | --- | --- | --- |
| Municípios em risco alto | 13,0% | 11,9% | 9,7% | **3,4%** | 4,8% |
| `ocorrencias_12m` (média) | 0,06 | 0,02 | **0,00** | **0,00** | **0,00** |
| `ocorrencias_uf_grupo_12m` | 14,5 | 4,8 | **0,00** | **0,00** | **0,00** |

O sistema anunciava um país cada vez mais seguro quanto mais longe se
perguntasse. E nenhuma métrica de acurácia denunciaria isso: todas são
medidas em anos que estão **dentro** da base, onde o defeito não existe.

### A correção

`src/atlas._ancora`: as janelas para trás param no fim da base. É a hipótese
padrão em previsão com variáveis defasadas — o que não se observa recebe a
última observação disponível. O mês-alvo continua valendo para tudo que é
sazonal.

| Mês pedido | 09/2026 | 12/2026 | 01/2027 | 06/2027 | 12/2027 |
| --- | --- | --- | --- | --- | --- |
| Antes | 13,0% | 11,9% | 9,7% | 3,4% | 4,8% |
| **Depois** | 12,8% | **19,9%** | **29,3%** | 15,6% | **19,9%** |
| Diferença | −0,2% | +8,0% | **+19,6%** | +12,3% | +15,1% |

Depois da correção a previsão volta a variar por **estação** — janeiro é o
pior mês do país, o que bate com a estação chuvosa — em vez de variar por
distância até o fim da base.

### O preço, dito com todas as letras

Setembro de 2026 e setembro de 2027 passam a receber a **mesma** resposta.
Isso não é um defeito da correção: é o estado real do conhecimento. Sem dado
novo entre os dois, não existe nada no modelo que os distinga.

Quem quiser previsões diferentes para 2027 precisa de dado de 2026 — não de
um modelo melhor.

### O que isso não estraga

O treino inteiro está dentro da base, então a âncora nunca atua ali. O teste
`test_features_do_passado_nao_mudam_com_a_ancora` gera o dataset com e sem a
correção e exige que sejam idênticos, linha por linha.

---

## 5. Geografia estática: altitude, declividade e distância do rio

A ideia é a que qualquer pessoa levanta olhando o mapa: **cidade baixa, plana
e à beira de rio grande alaga mais; cidade de encosta íngreme escorrega mais.**
Nada disso estava no modelo — a única geografia que ele conhecia eram UF e
região, grossas demais para distinguir Manaus de Fortaleza.

E havia um motivo novo para tentar. Desde a correção da seção 4, consultar um
mês futuro congela o histórico no fim da base. Geografia não congela: a
altitude de Blumenau é a mesma em 2025 e em 2027. Se ela ajudasse, ajudaria
justamente onde o resto do modelo fica cego.

### Os dados, baixados e medidos

`dados/baixar_rios.py` traz a rede de rios do Natural Earth 1:10m — 185
trechos, 29 mil vértices, 100 rios nomeados. `dados/preparar_geografia.py`
cruza isso com a malha do IBGE e a grade de relevo que já estavam no
repositório, e produz nove variáveis por município: altitude média e mínima,
amplitude, declividade, área, latitude, longitude e distância até o rio mais
próximo (qualquer um, e só os grandes).

A conferência bate com a realidade: a soma das áreas dá 8.493.683 km² contra
8.510.000 oficiais, Campos do Jordão sai a 1.556 m, Manaus a 46 km de rio
grande, Fortaleza a 533 km.

### O resultado

Mesmo protocolo de sempre: janela expansiva, oito anos, as duas variantes nas
mesmas janelas e nas mesmas linhas.

| Ano | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | média |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sem geografia | 61,7% | 66,6% | 46,9% | 58,1% | 60,2% | 57,6% | 53,9% | 59,3% | **58,1%** |
| Com geografia | 62,6% | 66,3% | 45,7% | 58,5% | 59,3% | 58,0% | 54,5% | 60,4% | **58,2%** |
| Diferença | +0,9% | −0,3% | −1,3% | +0,5% | −0,9% | +0,3% | +0,6% | +1,1% | **+0,11%** |

**+0,11 ponto, 5 anos de 8, p = 0,358.** Reprovado — é ruído.

### A hipótese de resgate, também testada

Ainda restava um argumento: a geografia não ajudaria no conjunto todo, mas
ajudaria onde o histórico se cala. Separando as linhas de teste pelo tamanho
do histórico daquele par (município, tipo):

| Histórico do par | Linhas | Sem geografia | Com geografia | Diferença |
| --- | --- | --- | --- | --- |
| **Nenhum (0 ocorrências)** | 20.069 | 45,4% | 45,5% | **+0,1%** |
| Pouco (1 a 2) | 37.205 | 49,3% | 49,3% | −0,1% |
| Médio (3 a 9) | 25.531 | 58,2% | 58,4% | +0,3% |
| Muito (10 ou mais) | 15.424 | 63,9% | 64,0% | +0,1% |

**Nem ali.** Nas 20 mil linhas em que o modelo não tinha ocorrência nenhuma
para consultar, saber que o município é baixo, plano e ribeirinho rendeu um
décimo de ponto.

De quebra, a tabela mostra outra coisa: o modelo vale 63,9% onde há histórico
farto e 45,4% onde não há. Ele é, antes de tudo, uma máquina de histórico.

### Por que não funcionou

A explicação mais provável é a mesma da chuva do INMET: **a informação já
estava lá, por outro caminho.** O histórico de ocorrências de um município é,
em boa parte, a consequência da geografia dele. Um município que alagou trinta
vezes já disse ao modelo que fica perto de um rio — e disse melhor do que a
distância em quilômetros, porque o histórico embute também o tamanho da
cidade, a ocupação das margens e a existência de obras de contenção.

### O que ficou

Os dois scripts e os dois arquivos continuam no repositório: são baratos
(1,3 MB no total), reprodutíveis e podem servir a uma tentativa futura, com
alvo semanal ou com hidrografia fina. **Nenhuma das nove colunas entrou no
modelo**, e `src/esquema.py` não foi tocado.

---

## Resposta curta: quanto cada mudança rende, em porcentagem

| Mudança | Efeito na acurácia balanceada | Medido em |
| --- | --- | --- |
| **Gradient boosting** | **+1,0%** — aplicado | 6 anos |
| Geografia (altitude, declive, rio) | +0,1% | 8 anos |
| Gradient boosting + limiar ajustado | +0,1% | 6 anos |
| Floresta + limiar ajustado | −0,8% | 6 anos |
| Escolher hiperparâmetros pela CV aleatória | −1,1% | 1 partição |
| Decomposição hierárquica | −2,9% | 1 partição |
| Calibração isotônica | −3,5% | 1 partição |

**Uma ajuda; as outras seis, não.** E a que ajuda só apareceu quando a
medição passou de uma partição para seis anos — na medição única ela valia
+0,0%, e o crédito estava indo para o limiar, que na verdade atrapalha.

Fora desta tabela fica a correção da seção 4, que não é ganho de acurácia
nenhum: é conserto de um defeito que as métricas de acurácia não conseguiam
ver, porque todas elas são medidas dentro da base.

As duas mudanças que eu havia recomendado sem medir — CV aleatória para
escolher modelos e calibração das probabilidades — continuam sendo as duas
piores da lista.

Vale registrar a exceção que não é de acurácia: a decomposição hierárquica com
peso alto no evento grave perde 0,7 ponto de acurácia mas ganha **+12,8 pontos
na detecção de casos graves** (63,3% contra 50,5%). Para um sistema de alerta
essa troca pode valer — é decisão de projeto, não de estatística, e continua
disponível para quem quiser tomá-la.

### Por que quase nada funciona

Os resultados negativos se dividem em dois grupos, com causas diferentes.

**Os ajustes finos falham por deriva.** A base muda de comportamento ao longo
dos anos: a taxa de ocorrências registradas sobe de 19% (2010) para 34%
(2023), por aumento real de eventos e por melhora da notificação. Calibração,
limiar de decisão e hiperparâmetro escolhido por sorteio são todos números
aprendidos num período e aplicados no seguinte — e chegam lá desatualizados.
Repare que a única mudança aprovada não é um ajuste fino: é trocar o
algoritmo, que não carrega número calibrado de um ano para o outro.

**As variáveis novas falham por redundância.** Chuva do INMET: +0,0%.
Geografia: +0,1%. Os dois casos têm a mesma explicação — o histórico de
ocorrências de um município já é a *consequência* da chuva que cai ali e da
geografia em que ele está. O modelo não precisa saber que Manaus fica na beira
do Amazonas; ele sabe que Manaus alaga.

E há uma terceira hipótese, que a tabela por faixa de histórico sugere e este
projeto não tem como testar: parte do que o modelo prevê não é o desastre, e
sim **o registro do desastre**. O rótulo vem de documento oficial, e a
propensão de uma prefeitura a decretar emergência é administrativa, não
geográfica. Isso explicaria de uma vez por que variáveis físicas nunca rendem
e variáveis de histórico rendem sempre.

O ganho grande continua não estando aqui. Ele viria de dado novo que explique
o evento numa resolução que o mês não tem (chuva de 24 e 72 horas) ou de mudar
a resolução do alvo — não de afinar o modelo.

---

## O que foi e o que não foi alterado

**Alterado, por causa da seção 3:** o classificador em produção, de Random
Forest para gradient boosting, em `treinamento/treinar_modelo.py`
(`CONFIG_BOOSTING` e `--modelo`) e no `modelo/modelo.pkl` retreinado.
`src/validacao_temporal.py` ganhou um parâmetro `ajustar`, para que a
validação treine o modelo do mesmo jeito que o treino de produção.

**Alterado, por causa da seção 4:** `src/atlas._ancora`, que faz as janelas
históricas pararem no fim da base quando o mês pedido está além dela. É
correção de defeito, não ganho de acurácia.

**Não alterado:** `src/esquema.py`, o contrato de dados, o pré-processamento,
as features e a lista de colunas. A assinatura do esquema continua
`a3812804df3f148f` — o mesmo contrato de antes, inclusive depois da seção 5,
que mediu nove colunas novas e não aprovou nenhuma.

Os demais experimentos desta pasta continuam sendo só medição.
