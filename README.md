# Fecart 2026 — Previsão de Risco de Desastres Naturais

Sistema que estima o **tipo de desastre natural mais provável** para um
município a partir de condições climáticas e geográficas, usando um modelo
**Random Forest** treinado com scikit-learn e servido por uma API **FastAPI**.

Tudo roda **localmente**: o modelo é treinado e executado na própria máquina,
sem serviços pagos, sem chave de API e sem enviar dados para a internet.

> **Estado atual dos dados:** a base histórica real de desastres do Brasil
> ainda não foi incorporada. O projeto funciona hoje com **dados sintéticos**
> (fictícios), o que permite treinar, avaliar e demonstrar o sistema inteiro.
> A troca pela base real está documentada em [`dados/README.md`](dados/README.md)
> e não exige reescrever o código.

---

## Como rodar (primeira vez)

**1. Clonar o repositório**

```bash
git clone https://github.com/Joao5554/Fecart-2026-teste-2.git
cd Fecart-2026-teste-2
```

**2. Criar o ambiente virtual**

```bash
python -m venv .venv
```

**3. Ativar o ambiente virtual** (Windows)

```powershell
.venv\Scripts\activate
```

> Se aparecer o erro *"a execução de scripts foi desabilitada neste sistema"*,
> rode uma vez e abra um novo terminal:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

**4. Instalar as bibliotecas**

```bash
pip install -r requirements.txt
```

**5. Treinar o modelo**

```bash
python treinamento/treinar_modelo.py
```

Se ainda não houver dados, o script gera a base sintética sozinho. Ao final,
cria `modelos/modelo.pkl` e `modelos/modelo_metadados.json`.

**6. Subir a API**

```bash
uvicorn backend.app:app --reload
```

Acesse **http://127.0.0.1:8000/docs** para testar pelo navegador.

---

## Estrutura do projeto

```
Fecart 2026/
├── dados/
│   ├── exemplo/         base sintética (versionada, para o projeto rodar após o clone)
│   ├── bruto/           base real (não vai para o GitHub)
│   └── README.md        formato esperado dos dados e onde obtê-los
├── treinamento/
│   ├── esquema.py             contrato dos dados — fonte única da verdade
│   ├── gerar_dados_exemplo.py gerador da base sintética
│   ├── preprocessamento.py    validação e transformações
│   └── treinar_modelo.py      treina, avalia e salva o modelo
├── backend/
│   ├── esquemas.py      modelos de entrada e saída da API
│   └── app.py           API FastAPI
├── modelos/             modelo treinado (gerado; não versionado)
├── testes/              testes automatizados
├── requirements.txt
└── README.md
```

### Por onde começar a mexer

| Quero... | Arquivo |
| --- | --- |
| Mudar as colunas dos dados | `treinamento/esquema.py` |
| Mudar os parâmetros do Random Forest | `treinamento/treinar_modelo.py` |
| Criar ou alterar endpoints | `backend/app.py` |
| Entender o formato dos dados | `dados/README.md` |

O arquivo `treinamento/esquema.py` é a **fonte única da verdade**: quem define
as colunas, as faixas de valores e as classes. O treinamento, a API e os testes
leem tudo dele, então uma mudança lá se propaga para o projeto inteiro.

---

## Endpoints da API

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/` | Informações básicas e status do modelo |
| `GET` | `/saude` | Verificação rápida de que está tudo no ar |
| `GET` | `/modelo/info` | Quando foi treinado, com quais dados e seu desempenho |
| `GET` | `/opcoes` | Campos e valores aceitos (útil para montar o formulário do front-end) |
| `POST` | `/prever` | Previsão para uma observação |
| `POST` | `/prever-lote` | Previsão para várias observações de uma vez |

### Exemplo de resposta do `/prever`

```json
{
  "tipo_desastre_previsto": "deslizamento",
  "descricao": "Movimento de massa / deslizamento de encosta",
  "confianca": 0.679,
  "probabilidade_algum_desastre": 0.982,
  "nivel_risco": "muito_alto",
  "probabilidades": {
    "deslizamento": 0.679,
    "inundacao": 0.138,
    "tempestade": 0.071,
    "estiagem_seca": 0.070,
    "incendio_florestal": 0.023,
    "nenhum": 0.018
  }
}
```

---

## Testes

```bash
pytest
```

Os testes verificam que o esquema do treinamento e o da API continuam
sincronizados, que a geração de dados é reprodutível, que o modelo aprende
mais do que o acaso e que a API recusa entradas inválidas.

**Rode os testes antes de todo commit.** Eles são a proteção do projeto contra
alterações que quebram alguma parte sem ninguém perceber.

---

## Como o projeto mantém a integridade

Alguns cuidados deliberados para o projeto continuar confiável com várias
pessoas mexendo nele:

- **Pré-processamento dentro do modelo.** As transformações são salvas junto
  com o Random Forest no `.pkl`, então a API aplica exatamente o mesmo
  tratamento usado no treino.
- **Metadados do modelo.** Cada treino grava versão, data, métricas, ambiente
  e o hash SHA-256 do arquivo de dados — dá para provar com qual base um
  modelo foi treinado.
- **Verificação de versão.** Se o esquema mudar e o modelo local estiver
  velho, a API recusa e diz para retreinar, em vez de prever errado calado.
- **Validação dos dados.** O treinamento confere as colunas e os tipos antes
  de começar, e falha com mensagem clara.
- **`.gitattributes`.** Padroniza quebras de linha entre Windows, Linux e macOS.
- **`.gitignore`.** O `.venv` e o `modelo.pkl` não vão para o GitHub; cada
  pessoa gera os seus a partir do `requirements.txt` e do treinamento.

---

## O que ainda falta

- [ ] Incorporar a base histórica real (ver [`dados/README.md`](dados/README.md))
- [ ] Reavaliar as métricas com os dados reais
- [ ] Front-end para consultar o modelo pelo navegador
- [ ] Gráficos de apoio para a apresentação da feira

---

## Fluxo de trabalho no Git

Antes de começar a programar, pegue as alterações dos colegas:

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

Se instalar uma biblioteca nova, atualize o `requirements.txt`:

```bash
pip freeze > requirements.txt
```
