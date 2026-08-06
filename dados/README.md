# Pasta de dados

O treinamento espera um arquivo `dados/dados.csv` no formato definido em
[`src/esquema.py`](../src/esquema.py).

Os CSVs desta pasta **não vão para o Git** (ver `.gitignore`): a base real é
grande demais, e a sintética é reproduzível por script.

## Enquanto a base real não chega

```bash
python dados/gerar_dados_sinteticos.py
```

Gera ~26 mil linhas inventadas, no formato exato do contrato. Servem **só**
para testar se o pipeline funciona. Nenhum número obtido com esses dados vale
como resultado — não use na apresentação.

## Formato esperado

Uma linha = **um município, em um mês, para um tipo de desastre**.

| codigo_ibge | municipio  | ano  | mes | cobrade_grupo | ... | nivel_risco |
| ----------- | ---------- | ---- | --- | ------------- | --- | ----------- |
| 3303906     | Petropolis | 2024 | 2   | DESLIZAMENTO  | ... | alto        |
| 3303906     | Petropolis | 2024 | 2   | INUNDACAO     | ... | medio       |
| 3303906     | Petropolis | 2024 | 3   | DESLIZAMENTO  | ... | baixo       |

O mesmo município aparece repetidas vezes — uma por mês e por tipo de
desastre. É isso que permite um único modelo cobrir todos os tipos.

Para ver a lista completa de colunas, com unidade e faixa de cada uma:

```bash
python -m src.esquema
```

## Onde conseguir os dados reais

O dataset final vem da junção de várias fontes públicas, todas com o
**código IBGE do município** como chave de ligação.

### 1. Histórico de desastres — a base principal

**S2iD — Sistema Integrado de Informações sobre Desastres** (SEDEC/MIDR)
<https://s2id.mi.gov.br>

É de onde vêm as colunas de histórico (`ocorrencias_12m`,
`ocorrencias_total_historico`, `decretos_emergencia_5anos`,
`media_afetados_historico`, `danos_materiais_historico_reais`) e, principalmente,
**o rótulo `nivel_risco`**.

O S2iD publica registros de ocorrência com data, município, código COBRADE,
danos humanos e prejuízos declarados. Também vale olhar o
[Atlas Digital de Desastres no Brasil](http://atlasdigital.mi.gov.br), que
disponibiliza os mesmos dados já consolidados e mais fáceis de baixar.

### 2. Dados climáticos

- **INMET — Banco de Dados Meteorológicos**: <https://bdmep.inmet.gov.br>
  Chuva, temperatura, umidade e vento por estação. As normais climatológicas
  (1991–2020) servem para calcular `anomalia_chuva_percentual`.
- **CEMADEN**: <https://www.cemaden.gov.br/mapainterativo/>
  Pluviômetros automáticos e umidade do solo, com resolução melhor que a do
  INMET em área urbana.
- **ANA — HidroWeb**: <https://www.snirh.gov.br/hidroweb/>
  Nível e vazão dos rios. Só existe onde há estação — daí `nivel_rio_m`
  aceitar valor vazio.

### 3. Dados do município

- **IBGE** (<https://www.ibge.gov.br>): área, população, densidade, biomas e
  malha municipal. O IBGE também publica o levantamento de
  **domicílios em áreas de risco**, que alimenta
  `percentual_domicilios_area_risco`.
- **Altitude e declividade**: modelo de elevação SRTM/TOPODATA (INPE) ou
  cartas geotécnicas da CPRM.
- **Cobertura vegetal**: MapBiomas (<https://mapbiomas.org>) ou TerraBrasilis
  (INPE), para o `indice_vegetacao`.

## Como definir o `nivel_risco` (a parte mais delicada)

O S2iD registra **o que aconteceu**, não "o nível de risco". O rótulo precisa
ser construído a partir dos registros, e essa decisão é metodológica — vale
descrevê-la na apresentação, porque é o coração do trabalho.

Uma regra defensável, a partir dos danos declarados no próprio S2iD:

| nivel_risco | critério no mês seguinte ao das features                          |
| ----------- | ----------------------------------------------------------------- |
| `baixo`     | nenhuma ocorrência registrada                                     |
| `medio`     | ocorrência registrada, sem decreto de emergência                   |
| `alto`      | ocorrência com decreto de emergência ou calamidade, ou com mortos  |

**Cuidado com vazamento temporal.** As features de um mês precisam prever o
mês *seguinte*. Se o rótulo de fevereiro for construído com a chuva de
fevereiro, o modelo aprende a "prever" o passado e a acurácia sai alta e
inútil. Ao montar o CSV, desloque o alvo em um mês.

Pelo mesmo motivo, quando a base real entrar, vale trocar o
`train_test_split` aleatório por uma **divisão temporal** (treinar até 2022,
testar em 2023–2024). É mais honesto: é assim que o sistema será usado.
