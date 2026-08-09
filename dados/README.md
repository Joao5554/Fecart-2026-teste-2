# Dados do projeto

Esta pasta guarda os dados usados no treinamento do modelo.

```
dados/
├── exemplo/    dados SINTÉTICOS (fictícios), versionados no Git
└── bruto/      base histórica REAL (não vai para o GitHub)
```

## Situação atual

Enquanto a base histórica real de desastres naturais do Brasil não está
disponível, o projeto usa dados **sintéticos** gerados por
`treinamento/gerar_dados_exemplo.py`.

Esses dados **não são reais**. Eles existem para que todo o sistema
(treinamento, avaliação e API) já funcione, seja testado e possa ser
apresentado. As métricas obtidas com eles medem o funcionamento do
pipeline, não a realidade dos desastres no Brasil.

O modelo treinado registra a origem dos dados em
`modelos/modelo_metadados.json` e a API avisa sobre isso no endpoint
`/modelo/info`, para que ninguém confunda demonstração com resultado real.

## Como trocar pelos dados reais

Quando a base real estiver pronta, são **três passos**:

1. Salve o arquivo como `dados/bruto/ocorrencias.csv`.
2. Ajuste, se necessário, as colunas em `treinamento/esquema.py`.
3. Rode novamente:

   ```bash
   python treinamento/treinar_modelo.py
   ```

O treinamento detecta o arquivo real automaticamente e passa a usá-lo no
lugar do sintético — nenhuma outra alteração de código é necessária.

## Formato esperado do CSV

Uma linha por **município e mês observado**. Separador vírgula, decimal
com ponto, codificação UTF-8.

### Colunas de entrada

| Coluna | Tipo | Unidade | Descrição |
| --- | --- | --- | --- |
| `uf` | texto | — | Sigla do estado (`SP`, `RJ`, `BA`, ...) |
| `regiao` | texto | — | `Norte`, `Nordeste`, `Centro-Oeste`, `Sudeste`, `Sul` |
| `bioma` | texto | — | `Amazonia`, `Caatinga`, `Cerrado`, `Mata Atlantica`, `Pampa`, `Pantanal` |
| `mes` | inteiro | 1–12 | Mês de referência |
| `precipitacao_mm` | decimal | mm | Chuva acumulada no mês |
| `precipitacao_max_24h_mm` | decimal | mm | Maior chuva em 24 h no mês |
| `dias_com_chuva` | inteiro | dias | Dias com chuva no mês |
| `temperatura_media_c` | decimal | °C | Temperatura média |
| `umidade_relativa_pct` | decimal | % | Umidade relativa média |
| `rajada_vento_max_kmh` | decimal | km/h | Maior rajada de vento |
| `altitude_m` | decimal | m | Altitude média do município |
| `declividade_media_pct` | decimal | % | Declividade média do terreno |
| `densidade_demografica_hab_km2` | decimal | hab/km² | Densidade demográfica |
| `pct_area_urbana` | decimal | % | Percentual de área urbana |
| `indice_vegetacao_ndvi` | decimal | 0–1 | Índice de vegetação NDVI |

### Coluna alvo

`tipo_desastre`, com um destes valores:

| Valor | Significado |
| --- | --- |
| `nenhum` | Nenhum desastre relevante no período |
| `estiagem_seca` | Estiagem ou seca prolongada |
| `inundacao` | Inundação, enxurrada ou alagamento |
| `deslizamento` | Movimento de massa / deslizamento |
| `tempestade` | Tempestade, vendaval ou granizo |
| `incendio_florestal` | Incêndio florestal |

A validação em `treinamento/preprocessamento.py` confere essas colunas e
interrompe o treinamento com uma mensagem clara caso algo não bata.

## Onde buscar os dados reais

Fontes públicas brasileiras que podem ser combinadas para montar a base:

- **S2ID / Atlas Digital de Desastres no Brasil** (Defesa Civil Nacional) —
  registros históricos de ocorrências com classificação COBRADE, que vira
  a coluna `tipo_desastre`.
- **CEMADEN** — monitoramento e alertas de desastres naturais.
- **INMET (BDMEP)** — séries históricas de chuva, temperatura, umidade e vento
  por estação meteorológica.
- **IBGE** — população, área e densidade demográfica dos municípios.
- **TOPODATA / INPE** — altitude e declividade do terreno.

O caminho usual é juntar tudo por **município + mês**: as ocorrências do
S2ID viram o alvo e as demais fontes viram as colunas de entrada. Meses
sem ocorrência registrada entram como `nenhum` — essa classe é essencial,
pois sem ela o modelo não aprende a diferenciar situação normal de risco.
