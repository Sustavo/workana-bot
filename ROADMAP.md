# Roadmap: Auto-Proposta Workana

## Contexto

Você quer automatizar o envio de propostas em vagas no `workana.com`. O fluxo é: o bot loga na sua conta, busca vagas que batem com critérios (categoria, orçamento, idioma), gera uma proposta personalizada para cada uma usando IA (com base na descrição da vaga e no seu perfil), e envia a proposta — registrando em banco local para não duplicar.

**Avisos importantes antes de começar:**
- Os Termos de Uso do Workana provavelmente proíbem automação. Risco real de banimento da sua conta. Mitigação recomendada: rodar em modo **"semi-automático"** (gerar a proposta, mostrar para você revisar, e só enviar com sua aprovação) em vez de envio direto. Dá pra ter um toggle `AUTO_SUBMIT=false` por padrão.
- O Workana usa **Cloudflare** (visto em `cf.wkncdn.com`). Pode ter Turnstile/desafios. Playwright lida com isso melhor que `requests`/Selenium puro.
- Limite forte de quantas propostas por dia (configurável) para parecer humano e não estourar o limite que o próprio Workana impõe a freelancers.

## Stack Recomendada

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | **Python 3.11+** | Ecossistema maduro pra scraping + IA, sintaxe limpa |
| Browser automation | **Playwright** (`playwright` lib) | Lida com Cloudflare, JS dinâmico, headless/headful, persistência de sessão |
| Geração de proposta | **Claude API** (`anthropic` SDK) | Gera proposta personalizada a partir da descrição da vaga + seu perfil; uso de prompt caching para baratear |
| Persistência | **SQLite** (built-in) | Tracking de vagas já vistas / propostas enviadas, sem precisar servidor |
| Config | **YAML** + `.env` (`python-dotenv`) | Filtros e perfil em YAML, segredos em `.env` |
| Logging | `loguru` | Setup simples, rotação automática |
| Agendamento | `cron` (Linux) ou `APScheduler` | Rodar a cada X horas |

**Alternativa**: Node.js + Playwright. Vai bem também, mas Python tem integração mais direta com Claude SDK e libs de NLP se quisermos enriquecer depois.

## Estrutura do Projeto

```
workana-screp/
├── .env                        # Segredos (NÃO commitar)
├── .env.example                # Template público
├── .gitignore
├── requirements.txt
├── README.md
├── pyproject.toml
├── config/
│   ├── filters.yaml            # Critérios de filtragem de vagas
│   └── profile.yaml            # Seu perfil profissional
├── templates/
│   └── proposals_examples.md   # Exemplos de propostas suas (input do AI)
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entrypoint CLI
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── session.py          # Setup Playwright, persistência cookies
│   │   └── auth.py             # Login + 2FA
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── jobs_list.py        # Lista de vagas paginada
│   │   ├── job_detail.py       # Página de detalhe da vaga
│   │   └── proposal_form.py    # Submissão do formulário de proposta
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── generator.py        # Claude API para gerar proposta
│   │   └── prompts.py          # Prompts versionados
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql
│   │   └── tracker.py          # CRUD: vagas vistas, propostas enviadas
│   ├── filters/
│   │   └── matcher.py          # Decide se uma vaga "bate" com seus critérios
│   └── utils/
│       ├── delays.py           # Sleeps humanos (jitter aleatório)
│       └── logger.py
├── tests/
│   ├── fixtures/
│   │   └── pages_html/         # HTML salvos que você vai me mandar
│   └── test_*.py
└── data/
    ├── workana.db              # SQLite (gitignored)
    └── storage_state.json      # Cookies/sessão do Playwright (gitignored)
```

## ⚠️ O Que Preciso Que Você Me Envie

Esta é a parte central do roadmap — sem isso eu não consigo escrever os seletores corretos nem ajustar o fluxo. Junte tudo numa pasta e me manda.

### 1. Credenciais e Chaves (texto, **não commit**)
- [ ] **Email do Workana** (o que você usa pra logar)
- [ ] **Senha do Workana**
- [ ] **Tem 2FA ativado?** Sim/Não. Se sim, qual método (SMS, app autenticador, email)?
- [ ] **Anthropic API key** (em `https://console.anthropic.com/settings/keys`). Se não tem, crio o snippet de cadastro
- [ ] **Tem alguma assinatura paga no Workana?** (Plus / Plus+) — isso muda o limite de bids/mês

### 2. Screenshots (PNG, tela inteira, **logado** na sua conta)
Tire com `F12 → Ctrl+Shift+P → "Capture full size screenshot"` no DevTools (Chrome/Firefox) ou com a extensão "GoFullPage". Não use print de tela do SO — quero a página inteira renderizada.

- [ ] `01_login.png` — página `workana.com/login` (deslogado)
- [ ] `02_dashboard.png` — primeira página depois de logar
- [ ] `03_jobs_feed.png` — lista de vagas (`/jobs?language=...`)
- [ ] `04_jobs_feed_filters_open.png` — mesma página com painel de filtros aberto
- [ ] `05_job_detail.png` — clicando em uma vaga qualquer, página de detalhe
- [ ] `06_proposal_form.png` — clicando em "Enviar proposta" / "Hacer una propuesta", formulário aberto
- [ ] `07_proposal_form_filled.png` — mesmo formulário preenchido por você manualmente (só pra eu ver os campos típicos)
- [ ] `08_my_proposals.png` — página que lista as propostas que você já enviou
- [ ] `09_profile_public.png` — seu perfil público
- [ ] `10_bid_limit.png` — algum lugar que mostra "X de Y propostas usadas este mês" (se existir)

### 3. HTMLs Completos (Right-click → "Save Page As" → "Webpage, Complete")
Salva no Chrome/Firefox depois de logar. Quero os arquivos `.html` e a pasta de assets junto. Isso me dá os seletores CSS/XPath reais.

- [ ] `login.html` — página de login
- [ ] `jobs_feed.html` — lista de vagas com pelo menos 5-10 cards visíveis
- [ ] `job_detail.html` — uma vaga aberta (qualquer uma)
- [ ] `proposal_form.html` — formulário de proposta aberto
- [ ] `my_proposals.html` — suas propostas enviadas

**Alternativa mais limpa**: abra DevTools → aba "Elements" → clica com botão direito no `<html>` → "Copy → Copy outerHTML" → cola num `.html`. Esse modo pega o DOM renderizado pós-JS, que é o que o Playwright vê.

### 4. URLs Exatas
Cole aqui as URLs reais que você usa, com query strings:

- [ ] URL da lista de vagas filtrada como você gosta (ex: `https://www.workana.com/jobs?category=...&language=pt&...`)
- [ ] URL de uma vaga de exemplo
- [ ] URL do seu perfil público

### 5. Seu Perfil Profissional (vai virar `config/profile.yaml`)
Texto livre, eu estruturo. Quero saber:

- [ ] **Nome profissional** que aparece nas propostas
- [ ] **Áreas/categorias** que você atua (ex: "Desenvolvimento Web", "IA & Machine Learning")
- [ ] **Skills principais** (stack: Python, React, etc.)
- [ ] **Idiomas** que você fala (pt, en, es) — afeta para que vagas pode propor
- [ ] **Valor/hora** (ou faixa, em USD e BRL)
- [ ] **Tempo de experiência**
- [ ] **Links de portfólio** (github, site, behance, linkedin)
- [ ] **Bio curta** (2-3 frases que você usaria em proposta)
- [ ] **O que você NÃO faz** (ex: "não pego WordPress", "não trabalho com PHP legado") — pra IA filtrar

### 6. Critérios de Filtro (vai virar `config/filters.yaml`)
- [ ] **Categorias de interesse** (lista)
- [ ] **Categorias bloqueadas** (lista)
- [ ] **Orçamento mínimo / máximo** (USD)
- [ ] **Tipo de projeto preferido** (fixo / por hora / ambos)
- [ ] **Idioma da vaga** (pt / es / en)
- [ ] **Palavras-chave obrigatórias** no título/descrição (ex: ["python", "ia"])
- [ ] **Palavras-chave proibidas** (ex: ["urgent", "wordpress", "estudante"])
- [ ] **Máx. de propostas por dia** (sugestão: 5-10 pra parecer humano)
- [ ] **Janela horária** que pode rodar (ex: 08h-22h horário Brasil) — evita envio às 3h da manhã

### 7. Exemplos de Propostas Vencedoras (vai virar `templates/proposals_examples.md`)
- [ ] **3 a 5 propostas suas** que deram certo no passado. Cola tudo: descrição da vaga + texto da sua proposta. A IA vai aprender seu tom/estrutura. Anonimiza nomes de cliente se quiser.

### 8. Decisões de Comportamento
Responde sim/não:

- [ ] **Modo de operação inicial: semi-automático** (gera, te mostra, espera aprovação) ou **totalmente automático** (gera e envia direto)? **Forte recomendação: semi-automático nas 2-3 primeiras semanas**, até confiar
- [ ] Se semi-automático, como você quer revisar? (a) e-mail com link de aprovação, (b) arquivo local que você roda `python approve.py`, (c) Telegram bot
- [ ] Quer **rodar headless** (sem ver a janela) ou **headful** (vendo o browser trabalhar) no início pra debugar?
- [ ] Quer **agendar** com cron (ex: roda 4x/dia) ou rodar manualmente?

## Variáveis de Ambiente (`.env`)

Eu gero o `.env.example`; você preenche num `.env` que não vai pro git.

```bash
# Workana
WORKANA_EMAIL=seu@email.com
WORKANA_PASSWORD=sua_senha
WORKANA_2FA_METHOD=none          # none | totp | sms

# Claude API
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6  # custo/qualidade equilibrado

# Comportamento
AUTO_SUBMIT=false                # false = semi-automático (recomendado começar assim)
HEADLESS=false                   # true depois que estiver funcionando
MAX_PROPOSALS_PER_DAY=8
MIN_DELAY_SECONDS=45             # delay mínimo entre ações no browser
MAX_DELAY_SECONDS=180
RUN_WINDOW_START=08              # hora UTC-3
RUN_WINDOW_END=22

# Infra
DATABASE_PATH=./data/workana.db
STORAGE_STATE_PATH=./data/storage_state.json
LOG_LEVEL=INFO
LOG_FILE=./data/logs/run.log

# Notificação (se semi-automático via telegram)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## Fases de Implementação

| Fase | Entrega | Depende de você |
|---|---|---|
| **0. Bootstrap** | Estrutura de pastas, `requirements.txt`, `.env.example`, `.gitignore` | Nada — começo na hora |
| **1. Login + sessão** | Loga, salva cookies em `storage_state.json`, reaproveita | Credenciais (item 1), screenshots/HTML de login (itens 2 e 3) |
| **2. Scraping lista** | Lê vagas do feed paginado, salva no SQLite | HTML do feed (item 3), URL com filtros (item 4) |
| **3. Filtragem** | `matcher.py` aplica critérios do YAML | `filters.yaml` (item 6) |
| **4. Scraping detalhe** | Para cada vaga aprovada, lê página de detalhe completa | HTML de detalhe (item 3) |
| **5. Geração IA** | Claude gera proposta personalizada com prompt caching no perfil | `profile.yaml` (item 5), exemplos (item 7) |
| **6. Submissão** | Preenche e envia formulário (ou só prepara se `AUTO_SUBMIT=false`) | HTML do form (item 3), screenshot preenchido (item 2) |
| **7. Aprovação (se semi-auto)** | Telegram/email/CLI mostra preview e espera ok | Decisão item 8 |
| **8. Tracker + dedup** | SQLite registra tudo, evita repropor mesma vaga | — |
| **9. Anti-detecção** | Delays aleatórios, user-agent realista, mouse/scroll simulados | — |
| **10. Agendamento** | Cron + healthcheck | Decisão item 8 |

## Arquivos Críticos a Criar

- `src/browser/session.py` — único ponto de criação de `BrowserContext` com `storage_state`
- `src/browser/auth.py` — fluxo de login resiliente (detecta se já está logado)
- `src/scraper/jobs_list.py` — paginação + extração estruturada de cards
- `src/scraper/proposal_form.py` — **mais delicado**: campos do form mudam, precisa ser tolerante
- `src/ai/generator.py` — usar **prompt caching** do Claude no bloco de perfil + exemplos (cacheia ~95% dos tokens, custo despenca)
- `src/db/tracker.py` — `jobs_seen`, `proposals_sent`, `proposals_pending_approval`
- `src/filters/matcher.py` — função pura, fácil de testar

## Verificação (como vamos saber que funciona)

1. **Smoke test login**: rodar `python -m src.main login --headful` e ver o browser logar e parar na dashboard. Cookies persistidos.
2. **Smoke test scrape**: `python -m src.main scrape --limit 5` — imprime 5 vagas estruturadas (título, orçamento, link).
3. **Smoke test filtro**: `python -m src.main filter --dry-run` — lista quais das 5 passariam pelos seus critérios.
4. **Smoke test IA**: `python -m src.main draft <job_id>` — gera proposta sem enviar, imprime.
5. **Dry run completo**: `python -m src.main run --dry-run` — faz tudo, **exceto** clicar em "enviar". Salva preview em `data/previews/`.
6. **Run real**: com `AUTO_SUBMIT=true` e `MAX_PROPOSALS_PER_DAY=1` no começo, manda **uma** proposta de verdade e você confirma no Workana que apareceu.
7. **Teste de duplicata**: rodar 2x seguidas, garantir que a mesma vaga não é proposta de novo.

## Próximos Passos Imediatos

Quando você me mandar o material da seção "O Que Preciso Que Você Me Envie", eu já consigo:

1. Criar a estrutura de pastas e arquivos base (Fase 0)
2. Escrever `auth.py` baseado no HTML real do login que você mandar (Fase 1)
3. Escrever `jobs_list.py` baseado no HTML real do feed (Fase 2)

**Mínimo absoluto para começar a codar**: itens **1** (credenciais), **3** (HTMLs de login + feed + detalhe + form) e **5** (seu perfil em texto livre). Com isso eu construo o esqueleto funcional. O resto (filtros, exemplos de propostas, decisões de comportamento) você pode me mandar depois.
