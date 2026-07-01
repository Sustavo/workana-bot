# Guia completo — workana-screp

Bot **semi-automático** de propostas no Workana: lê o feed de vagas, filtra, gera a
proposta com IA (DeepSeek), você revisa no terminal e ele envia pelo browser.

> **Filosofia:** nada é enviado sem você aprovar. O fluxo é dividido em **2 fases** —
> primeiro gera rascunhos (não envia nada), depois você revisa e envia.

---

## Sumário

1. [Como funciona (visão geral)](#1-como-funciona-visão-geral)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Instalação](#3-instalação)
4. [Configuração](#4-configuração)
5. [Como usar (passo a passo)](#5-como-usar-passo-a-passo)
6. [Referência de todos os comandos](#6-referência-de-todos-os-comandos)
7. [Perfis de velocidade (anti-ban)](#7-perfis-de-velocidade-anti-ban)
8. [Proteções anti-ban (guard) e parada inteligente](#8-proteções-anti-ban-guard-e-parada-inteligente)
9. [Entendendo a saída (painel, logs, relatórios)](#9-entendendo-a-saída-painel-logs-relatórios)
10. [Banco de dados (estados das vagas)](#10-banco-de-dados-estados-das-vagas)
11. [Solução de problemas](#11-solução-de-problemas)
12. [Estrutura do projeto](#12-estrutura-do-projeto)

---

## 1. Como funciona (visão geral)

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  FASE 1 — scrape         │        │  FASE 2 — approve            │
│  python -m src.main      │        │  python approve.py           │
│  scrape                  │        │                              │
│                          │        │  1. Mostra cada rascunho     │
│  1. Abre o feed          │        │     (y/n/s/e)                │
│  2. Filtra as vagas      │ ─────▶ │  2. Abre o browser           │
│  3. Lê detalhe + média   │  SQLite│  3. Envia os aprovados       │
│  4. Gera proposta (IA)   │ drafts │     (ajusta valor ao mínimo, │
│  5. Salva como rascunho  │        │      confirma o envio)       │
│     NÃO ENVIA            │        │                              │
└─────────────────────────┘        └──────────────────────────────┘
```

- **Fase 1 (`scrape`)** só *gera rascunhos* e salva no banco. Não envia nada.
- **Fase 2 (`approve.py`)** mostra os rascunhos, você aprova/edita/rejeita, e só então
  o bot abre o browser e envia os aprovados.

---

## 2. Pré-requisitos

| Item | Detalhe |
|------|---------|
| **Python** | 3.11 ou superior (o ambiente atual usa 3.12) |
| **Google Chrome** | Instalado no sistema (o bot usa o Chrome real, não o Chromium). Já está em `/usr/bin/google-chrome`. |
| **Conta Workana** | Logada manualmente na primeira execução |
| **Chave de IA** | De **um** provedor à sua escolha: DeepSeek, OpenAI, Google ou Qwen (ver seção 4.5 com preços) |

---

## 3. Instalação

> O projeto **já tem** uma `.venv` e as dependências instaladas. Esta seção é para
> reinstalar do zero (outra máquina, ou se quebrar algo).

```bash
cd /home/gustavo-sousa/Estudos/workana-screp

# 1. Cria e ativa o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instala as dependências Python
pip install -r requirements.txt

# 3. Garante o Chrome para o Playwright (se ainda não tiver o Google Chrome)
python -m playwright install chrome

# 4. Cria seu .env a partir do exemplo
cp .env.example .env
# edite o .env e cole DEEPSEEK_API_KEY e WORKANA_USER_ID (ver seção 4)
```

> **Dica:** você pode rodar os comandos **sem ativar a venv** usando o caminho direto
> `.venv/bin/python` no lugar de `python`. Ex.: `.venv/bin/python -m src.main scrape`.

---

## 4. Configuração

São 3 arquivos: `.env` (segredos e comportamento), `config/profile.yaml` (seu perfil)
e `config/filters.yaml` (critérios de filtragem).

### 4.1. `.env` — variáveis de ambiente

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `AI_PROVIDER` | `deepseek` | **Qual IA usar:** `deepseek`, `openai`, `google` ou `qwen` (preços na seção 4.5). |
| `DEEPSEEK_API_KEY` | — | Chave do DeepSeek (obrigatória **se** `AI_PROVIDER=deepseek`). |
| `OPENAI_API_KEY` | — | Chave da OpenAI (obrigatória **se** `AI_PROVIDER=openai`). |
| `GOOGLE_API_KEY` | — | Chave do Google/Gemini (obrigatória **se** `AI_PROVIDER=google`; aceita `GEMINI_API_KEY`). |
| `QWEN_API_KEY` | — | Chave do Qwen/DashScope (obrigatória **se** `AI_PROVIDER=qwen`; aceita `DASHSCOPE_API_KEY`). |
| `<PROVIDER>_MODEL` | mais barato | Troca o modelo de um provedor (ex.: `OPENAI_MODEL=gpt-4.1-nano`). Vazio = padrão da seção 4.5. |
| `AI_MODEL` | — | Override **global** de modelo (ganha de qualquer `<PROVIDER>_MODEL`). |
| `AI_BASE_URL` | — | Endpoint custom (proxy/gateway, ou outra região do Qwen). Vazio = endpoint padrão do provedor. |
| `WORKANA_JOBS_URL` | feed de TI | URL do feed **já com seus filtros** (categoria/idioma). |
| `WORKANA_USER_ID` | — | Hash do seu perfil (ver 4.4). Usado para ler conexões restantes. |
| `CHROME_PROFILE_DIR` | `./data/chrome-profile` | Pasta do perfil do Chrome (guarda o login). **Não apague.** |
| `HEADLESS` | `false` | `false` = mostra a janela do browser (recomendado). `true` = sem janela. |
| `MAX_DRAFTS_PER_RUN` | `8` | Máx. de rascunhos gerados por execução do `scrape`. |
| `SPEED_PROFILE` | `equilibrado` | Perfil de velocidade: `conservador`, `equilibrado` ou `rapido` (ver seção 7). |
| `GUARD_ENABLED` | `true` | Liga o detector de bloqueio/captcha (recomendado `true`). |
| `SUBMIT_REDIRECT_TIMEOUT_MS` | `25000` | Tempo (ms) para confirmar o envio de uma proposta. |
| `FILL_DELIVERY_TIME` | `false` | Se preenche o campo "Prazo de entrega" no formulário. |
| `DATABASE_PATH` | `./data/workana.db` | Caminho do banco SQLite. |
| `LOG_LEVEL` | `INFO` | Nível do log no terminal (`DEBUG` para depurar). |
| `LOG_FILE` | `./data/logs/run.log` | Arquivo de log completo (sempre em DEBUG). |

**Overrides finos de velocidade** (opcionais — descomente no `.env` só se quiser ajustar
manualmente; ganham do `SPEED_PROFILE`): `MIN_DELAY_SECONDS`, `MAX_DELAY_SECONDS`,
`LONG_PAUSE_CHANCE`, `LONG_PAUSE_MIN_SECONDS`, `LONG_PAUSE_MAX_SECONDS`,
`MAX_ACTIONS_PER_HOUR`.

### 4.2. `config/profile.yaml` — seu perfil

Usado pela IA para escrever a proposta e calcular o valor. Campos importantes:

| Campo | O que faz |
|-------|-----------|
| `name`, `headline`, `bio`, `skills` | Identidade usada no texto da proposta. |
| `do_not_take` | Lista de coisas que você NÃO faz → o `matcher` veta essas vagas. |
| `featured_portfolio_ids` | **Os 3 IDs** de itens do portfólio Workana marcados como destaque no envio (ver 4.4). Vazio = pula essa etapa. |
| `bid_discount_pct` | Desconto sobre a média dos concorrentes (`0.10` = 10% abaixo). |
| `max_bid_brl` | Teto absoluto do valor do bid (rede de segurança). |
| `max_hourly_rate_brl` | Teto do valor por hora, quando o formulário é "por hora". |

### 4.3. `config/filters.yaml` — critérios de filtragem

| Campo | O que faz |
|-------|-----------|
| `blocked_keywords` | Se a palavra aparece no título/skills, **descarta** a vaga. |
| `required_keywords_any` | Se preenchido, a vaga só passa se tiver **alguma** dessas palavras. |
| `blocked_categories` | Categorias vetadas (o match ignora ordem/conector: "Vendas e Marketing" casa com "Marketing e Vendas"). |
| `allowed_categories` | Se preenchido, só passam vagas dessas categorias. |
| `min_budget_usd` | Orçamento mínimo (na moeda exibida, normalmente R$). `0` = sem mínimo. |
| `max_competing_proposals` | Pula vagas "saturadas" com mais propostas que isso. |

> Filtros baratos (palavra-chave, nº de propostas) rodam **no card do feed**. Filtros de
> categoria e orçamento rodam **na página de detalhe** da vaga (onde esses dados aparecem).

### 4.4. Como pegar os IDs do Workana

- **`WORKANA_USER_ID`**: abra seu perfil em `https://www.workana.com/freelancer/<HASH>` —
  o `<HASH>` na URL é o seu user id.
- **`featured_portfolio_ids`**: no seu perfil, inspecione (F12) um item de portfólio e
  procure o atributo `data-id` (ou o id na URL do projeto). Pegue 3 e cole no
  `profile.yaml`.

### 4.5. Provedores de IA (qual escolher e quanto custa)

O bot fala com **um** provedor por vez, escolhido em `AI_PROVIDER`. Todos usam o mesmo
SDK (`openai`) por baixo, então trocar é só mudar a env e pôr a chave do escolhido.
Cada um já vem com o **modelo mais barato** como padrão.

| `AI_PROVIDER` | Modelo padrão (mais barato) | US$/1M entrada | US$/1M saída | Onde pegar a chave | Tem teste grátis? |
|---------------|-----------------------------|----------------|--------------|--------------------|-------------------|
| `deepseek` | `deepseek-v4-flash` | **0,14** | **0,28** | https://platform.deepseek.com/api_keys | Não — **pré-pago**, precisa pôr saldo |
| `openai` | `gpt-5-nano` | **0,05** | **0,40** | https://platform.openai.com/api-keys | Não — pré-pago |
| `google` | `gemini-2.5-flash-lite` | **0,10** | **0,40** | https://aistudio.google.com/app/apikey | **Sim** — free tier com limites |
| `qwen` | `qwen-flash` | **0,05** | **0,40** | https://bailian.console.alibabacloud.com (DashScope) | **Sim** — 1M tokens grátis/modelo (90 dias, endpoint intl) |

> Preços USD por **1 milhão de tokens** (tier pago/standard, texto), conferidos em jun/2026
> nas páginas oficiais. Uma proposta gasta ~1–2 mil tokens, então o custo por proposta é
> de **frações de centavo** em qualquer um deles. Para referência: ~50 propostas/semana ≈
> alguns centavos de dólar por mês.

**Para começar barato/sem cartão:** use `google` (free tier no Google AI Studio) ou `qwen`
(1M tokens grátis). **Menor custo pago:** `openai` (`gpt-5-nano`) e `qwen` empatam em
US$ 0,05 de entrada.

**Trocar o modelo de um provedor** (opcional): descomente o `<PROVIDER>_MODEL` no `.env`.
Alternativas úteis:
- **DeepSeek:** `deepseek-v4-pro` (melhor qualidade, ~US$ 0,44/0,87).
- **OpenAI:** `gpt-4.1-nano` (US$ 0,10/0,40) — não tem as restrições da família GPT-5 (que
  trava temperatura e usa `max_completion_tokens`); o bot já lida com isso automaticamente.
- **Google:** `gemini-2.5-flash` (mais caro, melhor qualidade).
- **Qwen:** `qwen-plus` (mais caro, melhor qualidade).

**Detalhes que o bot já trata sozinho** (não precisa fazer nada): a família GPT-5 do OpenAI
exige `max_completion_tokens` e temperatura fixa; o Qwen precisa rodar em modo *não-thinking*
pro JSON funcionar; DeepSeek/Qwen exigem a palavra "json" no prompt. Tudo isso está embutido
no `src/utils/config.py` (registro `AI_PROVIDERS`) e no `src/ai/generator.py`.

> **Qwen e regiões:** o padrão é o endpoint internacional (Singapura). Se sua chave for de
> outra região (China continental, EUA, HK), ajuste `AI_BASE_URL` no `.env` — as chaves
> **não** são intercambiáveis entre regiões.

---

## 5. Como usar (passo a passo)

### Fase 1 — gerar rascunhos

```bash
# com a venv ativada:
python -m src.main scrape

# escolhendo o ritmo na hora (sobrepõe o SPEED_PROFILE do .env):
python -m src.main scrape --speed conservador
```

O que acontece:

1. Abre o **Google Chrome**. **Na primeira vez**, se cair na tela de login: **logue
   manualmente** na janela, volte ao terminal e tecle **ENTER**. O login fica salvo em
   `data/chrome-profile/` e nas próximas vezes já entra logado.
2. Lê suas **conexões restantes** (plano Explorer = 52/semana).
3. Para cada vaga com botão "Fazer uma proposta": abre o detalhe + a página de insight
   (média dos concorrentes), aplica os filtros e gera a proposta com a IA.
4. Salva como **rascunho** no banco. **Não envia nada.**
5. Para ao atingir `MAX_DRAFTS_PER_RUN`.

Durante a execução, um **painel ao vivo** mostra: alvo/processados/gerados/pulados,
vaga atual, média dos concorrentes vs. valor escolhido, conexões restantes e ritmo/min.

### Fase 2 — revisar e enviar

```bash
python approve.py
# ou com ritmo específico:
python approve.py --speed conservador
```

1. Para cada rascunho pendente, mostra os dados da vaga e a proposta. Você responde:
   - **`y`** — aprova
   - **`n`** — rejeita (não volta a aparecer)
   - **`s`** — pula (volta a aparecer na próxima vez)
   - **`e`** — edita o texto/valor/prazo e aprova
2. Depois de revisar todos, o bot **abre o browser**, confirma o login e **envia os
   aprovados** um a um, com painel ao vivo (enviados/falhas).
3. No envio, para cada proposta ele:
   - lê o **lance mínimo** real e garante que o valor **nunca fica abaixo dele**
     (ex.: você pôs 1000, mínimo é 1050 → envia 1050);
   - **confirma** que o envio realmente aconteceu — se não confirmar, **não** marca como
     enviado e registra no relatório de falhas.

### Ver os rascunhos pendentes (sem abrir browser)

```bash
python -m src.main list-drafts
```

---

## 6. Referência de todos os comandos

| Comando | O que faz |
|---------|-----------|
| `python -m src.main scrape` | **Fase 1.** Gera rascunhos e salva no banco. Não envia. |
| `python -m src.main scrape --speed conservador\|equilibrado\|rapido` | Fase 1 escolhendo o ritmo. |
| `python -m src.main list-drafts` | Lista os rascunhos pendentes (valor + prazo). |
| `python -m src.main --help` | Ajuda da CLI. |
| `python -m src.main scrape --help` | Ajuda do comando `scrape` (mostra `--speed`). |
| `python approve.py` | **Fase 2.** Revisa (y/n/s/e) e envia os aprovados. |
| `python approve.py --speed conservador\|equilibrado\|rapido` | Fase 2 escolhendo o ritmo. |
| `python debug_insight.py <slug>` | Ferramenta de depuração: salva HTML/print/texto da página de insight de uma vaga (para investigar quando a média não é encontrada). Saída em `data/insights/debug/`. |
| `PYTHONPATH=. python tests/test_units.py` | Roda os testes de unidade (parsing de valor, filtros, perfis de velocidade). |
| `python -m pytest tests/ -q` | Roda os testes via pytest (se instalado). |

> O `<slug>` é o identificador da vaga na URL: `https://www.workana.com/job/<slug>`.

---

## 7. Perfis de velocidade (anti-ban)

O Workana usa Cloudflare e tem limites; ações rápidas demais aumentam o risco de bloqueio.
Escolha o ritmo por `--speed` (CLI) ou `SPEED_PROFILE` no `.env`.

| Perfil | Delay entre ações | Pausa longa ocasional | Teto de ações/hora | Quando usar |
|--------|-------------------|-----------------------|--------------------|-------------|
| **conservador** | 4–10s | 25–70s (18% das ações) | 40/h | Mais seguro. Rodar de fundo / sem pressa. |
| **equilibrado** *(padrão)* | 2.5–6s | 15–45s (12%) | 90/h | Bom meio-termo. |
| **rapido** | 0.5–1.5s | — | sem teto | Mais veloz, **maior risco de ban**. Use com parcimônia. |

---

## 8. Proteções anti-ban (guard) e parada inteligente

Com `GUARD_ENABLED=true`, após cada navegação o bot verifica sinais de bloqueio
(captcha/Cloudflare/Turnstile, "atividade suspeita", "acesso negado", HTTP 403/429/503,
redirect inesperado para login). Comportamento ao detectar problema:

| Situação | O que o bot faz |
|----------|-----------------|
| **Erro da API do DeepSeek** (saldo/402, chave inválida/401, ou indisponibilidade que sobreviveu aos retries) | **Aborta** a execução e salva o que já foi feito (não adianta continuar). |
| **Atividade suspeita no Workana** (captcha/login/bloqueio) | **Pausa** e pede para você resolver na janela do browser e teclar **ENTER**; depois re-verifica e continua. Se continuar bloqueado, aborta. |
| **Modo headless** (`HEADLESS=true`) | Como não dá para intervir, **aborta** ao detectar suspeita. |

> Por isso, para uso normal, deixe `HEADLESS=false` (você vê a janela e pode resolver
> captchas/logins).

---

## 9. Entendendo a saída (painel, logs, relatórios)

- **Painel ao vivo (terminal):** contadores de progresso em tempo real. Aparece quando
  `HEADLESS=false`.
- **Log completo:** `data/logs/run.log` (sempre em nível DEBUG, mesmo quando o terminal
  está em INFO). É aqui que você investiga erros.
- **Relatório de falhas de envio:** quando alguma proposta não é enviada, gera um arquivo
  em `data/reports/falhas-AAAAMMDD-HHMMSS.md` com a causa provável de cada falha
  (ex.: "valor abaixo do mínimo", "envio não confirmado").
- **Dumps de depuração:** HTML salvo em `data/insights/` (quando não acha a média) e em
  `data/insights/debug/` (quando não acha skills no form).

---

## 10. Banco de dados (estados das vagas)

Banco SQLite em `data/workana.db`, com 3 tabelas: `jobs_seen`, `drafts`, `submissions`.

**Estados de uma vaga (`jobs_seen.state`):**

```
open ──filtra+gera──▶ drafted ──aprova+envia──▶ sent
  │
  ├──▶ already_bid   (já existe proposta / sem botão de propor)
  └──▶ skipped       (vetada por um filtro)
```

**Status de um rascunho (`drafts.status`):** `pending` → `sent` (ou `rejected`).
Um envio que **não confirma** mantém o rascunho em `pending` (reaparece na próxima
revisão) — nunca é marcado como `sent` por engano.

**Inspecionar o banco:**

```bash
sqlite3 data/workana.db "SELECT slug, status FROM drafts;"
sqlite3 data/workana.db "SELECT slug, state FROM jobs_seen ORDER BY last_seen_at DESC LIMIT 20;"
sqlite3 data/workana.db "SELECT slug, amount, sent_at FROM submissions;"
```

---

## 11. Solução de problemas

| Sintoma | Causa provável / solução |
|---------|--------------------------|
| **"Sessão NÃO autenticada"** | Faça login manualmente na janela do browser e tecle ENTER no terminal. |
| **Aborta com erro do DeepSeek** | Saldo insuficiente (402), chave inválida (401) ou serviço fora após várias tentativas. Verifique `DEEPSEEK_API_KEY` e seu saldo em https://platform.deepseek.com. |
| **Pausou pedindo intervenção** | O Workana mostrou captcha/bloqueio. Resolva na janela e tecle ENTER. Se acontecer muito, use `--speed conservador`. |
| **Valor "errado" no envio** | Já corrigido: o bot ajusta o valor ao mínimo e confirma o envio. Se ainda houver falha, veja o relatório em `data/reports/`. |
| **Seletor não encontrado / form mudou** | O Workana atualizou o HTML. Rode com `LOG_LEVEL=DEBUG`, veja `data/logs/run.log` e os dumps em `data/insights/debug/`. |
| **Modal de portfólio não abre** | Verifique se `featured_portfolio_ids` está preenchido no `profile.yaml`. |
| **Quero depurar a média dos concorrentes** | `python debug_insight.py <slug>` e olhe os arquivos em `data/insights/debug/`. |

---

## 12. Estrutura do projeto

```
workana-screp/
├── src/
│   ├── main.py                 # CLI: scrape, list-drafts (+ --speed)
│   ├── browser/
│   │   ├── session.py          # Abre o Chrome, login, pausa inteligente
│   │   └── guard.py            # Detector de bloqueio/captcha/atividade suspeita
│   ├── scraper/
│   │   ├── jobs_list.py        # Cards do feed (+ nº de propostas e orçamento)
│   │   ├── job_detail.py       # Página da vaga (+ categoria)
│   │   ├── job_insight.py      # Média dos concorrentes
│   │   ├── profile.py          # Conexões restantes
│   │   └── bid_form.py         # Preenche e ENVIA a proposta (mínimo + confirmação)
│   ├── ai/
│   │   ├── prompts.py          # Instrução de sistema + prompt
│   │   └── generator.py        # Chamada ao DeepSeek (SDK openai, compatível)
│   ├── filters/matcher.py      # Decide se a vaga passa (card e detalhe)
│   ├── db/
│   │   ├── schema.sql          # Tabelas
│   │   └── tracker.py          # SQLite
│   ├── ui/dashboard.py         # Painel ao vivo (rich)
│   └── utils/
│       ├── config.py           # .env + perfis de velocidade
│       ├── delays.py           # Delays humanos + teto/hora
│       ├── number.py           # Parser de valores BR/US
│       ├── errors.py           # Exceções de parada
│       └── logger.py           # Logs (terminal + arquivo)
├── approve.py                  # Revisão interativa + envio
├── debug_insight.py            # Depuração da página de insight
├── config/
│   ├── profile.yaml            # Seu perfil
│   └── filters.yaml            # Critérios de filtragem
├── Templates/proposals_examples.md  # Exemplos de propostas (referência da IA)
├── tests/test_units.py         # Testes de unidade
├── data/                       # Banco, logs, perfil do Chrome, relatórios (gerado)
├── .env                        # Seus segredos/config (não versionar)
└── requirements.txt
```

---

### Fluxo resumido do dia a dia

```bash
source .venv/bin/activate
python -m src.main scrape --speed conservador   # 1. gera rascunhos
python -m src.main list-drafts                  # 2. (opcional) confere o que tem
python approve.py                               # 3. revisa e envia
```
