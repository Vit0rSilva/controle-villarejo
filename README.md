# Controle Villarejo — Estoque Automatizado via WhatsApp (Evolution API)

Sistema completo de **Controle de Estoque Automatizado via WhatsApp (Evolution API) com Painel Web** para operação de restaurante/pizzaria, construído com **Python 3.14**, **FastAPI**, **SQLAlchemy 2.0+ (Async)**, **PostgreSQL 16.15** e **RapidFuzz**.

---

## Principais Funcionalidades

1. **Recebimento via Webhook da Evolution API (`POST /api/v1/webhook/evolution`)**
   - Validação de segurança via `EVOLUTION_WEBHOOK_TOKEN` (headers `X-Webhook-Token`, `apikey`, `Authorization: Bearer` ou query param `?token=`).
   - Validação ativa de conexão e descoberta dinâmica de instância (`/instance/connectionState/{instance}` e `/instance/fetchInstances`).
2. **Máquina de Estados para Mensagens Orgânicas (`ParserService`)**
   - Remoção de emojis (`🥩`, `🐔`, `🦐`, `🍍`, `🧋`, `🥗`) e marcadores (`●`, `•`, `*`, `-`) preservando a estrutura de linhas.
   - Agrupamento multilinha de sub-atributos (`porcoes`, `aberto`, `cozido`, `ralado`, `cortado`, `panelas`, `vasilhas`) no produto pai.
   - Suporte a linhas sem dois-pontos (`Frango 15kg 🐔`, `Laranja 🍊 4L`, `Tomate grande 🍅 tem`), valores quebrados na linha seguinte (`Leite condensado zero lactose \n 06 uni`) e marcação de dados incompletos (`Salmão:\n 00 peça:` -> `is_incomplete_data = True`).
   - Suporte a sub-cabeçalhos (`Para Suco 🧋`, `FOLHAS`), troca de seção no meio da mensagem (`*SORVETES:`) e inferência automática de seção quando a mensagem não possui cabeçalho inicial.
3. **Prevenção de Erros de Digitação (`FuzzyService` + `RapidFuzz`)**
   - Higienização de caracteres repetidos (`Cifff` -> `Cif`), correções ortográficas (`Creme cheese` -> `Cream Cheese`, `100 porca` -> `100 porções`) e busca difusa (`score >= 82`) com registro automático em `aliases`.
4. **Detecção Inteligente de Falta (`StockStatus`)**
   - `CRITICAL` (Vermelho): Itens zerados (`00`) sem porções/abertos disponíveis ou marcados como `Fazer` / `Trazer` / `Acabou`.
   - `WARNING` (Amarelo/Laranja): Itens com peça bruta zerada (`00`) mas que ainda possuem porções ou unidades abertas em uso (ex: *"Bruto zerado (Restam 35 porções de 100g)"*), ou com termos `Pouco`, `Abaixo de meio caixote`, `Meia vasilha`.
   - `OK` (Verde): Quantidade positiva ou `Tem` sem indicadores críticos.
5. **Monitoramento de Atualização de 24 Horas por Seção**
   - Banner vermelho piscante e cards de saúde das seções no topo do Dashboard quando `last_updated_at` é nulo ou `> 24 horas`.

---

## Como Executar

### 1. Configurar Variáveis de Ambiente
```bash
cp .env.example .env
```

### 2. Executar Migrations do Banco (PostgreSQL 16.15)
```bash
alembic upgrade head
```
*(Em modo `development`, caso o PostgreSQL local ainda não esteja acessível, o sistema realiza fallback automático para `sqlite+aiosqlite:///./estoque_dev.db` para execução imediata).*

### 3. Popular o Banco com as 6 Mensagens Reais do Restaurante
```bash
python3 seed.py
```

### 4. Iniciar o Servidor Web + API
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- **Painel Web (Dashboard):** http://localhost:8000/
- **Documentação Interativa (Swagger UI):** http://localhost:8000/docs

### 5. Executar os Testes Automatizados
```bash
pytest -v
```
