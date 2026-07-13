# Fecart 2026

Projeto de IA com Random Forest, backend em FastAPI.

## Como rodar o projeto (primeira vez)

1. **Clonar o repositório**

   ```bash
   git clone https://github.com/Joao5554/Fecart-2026-teste-2.git
   cd Fecart-2026-teste-2
   ```

2. **Criar o ambiente virtual**

   ```bash
   python -m venv .venv
   ```

3. **Ativar o ambiente virtual** (Windows)

   ```powershell
   .venv\Scripts\activate
   ```

   > Se aparecer erro de "execução de scripts foi desabilitada", rode uma vez:
   > `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
   > e abra um novo terminal.

4. **Instalar as bibliotecas**

   ```bash
   pip install -r requirements.txt
   ```

## Estrutura do projeto

| Pasta / arquivo                  | O que é                                              |
| -------------------------------- | ---------------------------------------------------- |
| `dados/`                         | Datasets (CSV) usados no treinamento                 |
| `treinamento/treinar_modelo.py`  | Treina o Random Forest e gera o `modelo.pkl`         |
| `backend/app.py`                 | API FastAPI que serve as previsões do modelo         |
| `requirements.txt`               | Lista de bibliotecas com versões fixas               |

## Treinar o modelo

```bash
python treinamento/treinar_modelo.py
```

Lê os dados de `dados/dados.csv`, treina o modelo e salva o `modelo.pkl` na raiz do projeto.

## Rodar o backend

```bash
uvicorn backend.app:app --reload
```

Depois acesse <http://127.0.0.1:8000/docs> para testar a API pelo navegador.

## Fluxo de trabalho no git

Antes de começar a programar, pegue as mudanças mais recentes:

```bash
git pull origin main
```

Depois de alterar o código:

```bash
git status
git add .
git commit -m "Mensagem descrevendo a alteração"
git push origin main
```

Se instalar uma biblioteca nova, atualize o `requirements.txt`:

```bash
pip freeze > requirements.txt
```
