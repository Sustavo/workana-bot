# workana-screp

Semi-automatiza envio de propostas no Workana. Lê o feed, gera draft com DeepSeek, você aprova no terminal, ele envia via browser headful.

## Setup (uma vez só)

```bash
cd /home/gustavo-sousa/Estudos/workana-screp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
# Edita .env: cola DEEPSEEK_API_KEY e WORKANA_USER_ID
```

Edita também:
- `config/profile.yaml` — seu perfil (eu já preenchi com base no que você mandou; revisa links/IDs)
- `config/filters.yaml` — critérios de filtragem
- `Templates/proposals_examples.md` — já tem seus 6 exemplos
- `config/profile.yaml` → `featured_portfolio_ids` — **precisa preencher**: cole os 3 IDs dos itens do seu portfólio Workana que vão sempre virar "destaque" (pega via DevTools no perfil)

## Uso (toda vez)

### 1. Scrape + draft
```bash
python -m src.main scrape
```

Primeira execução: abre Chromium e fica numa tela do Workana. **Se cair na tela de login, loga manualmente**, volta no terminal e dá ENTER. O cookie fica em `data/chrome-profile/` e nas próximas vezes já vem logado.

O comando:
1. Visita o feed (`WORKANA_JOBS_URL` do `.env`)
2. Lê a quantidade de conexões restantes (Explorer = 52/semana)
3. Pra cada card com botão "Fazer uma proposta", visita a página da vaga + a página de insight
4. Joga tudo no DeepSeek → recebe `{content, amount_brl, delivery_time, hours_estimate}`
5. Salva como draft no SQLite

Para no `MAX_DRAFTS_PER_RUN` (padrão 8).

### 2. Aprovar e enviar
```bash
python approve.py
```

Pra cada draft pendente, mostra: dados da vaga, média dos concorrentes, valor proposto, texto. Você responde:
- `y` — aprova
- `n` — rejeita
- `s` — pula (volta a aparecer próxima vez)
- `e` — edita texto/valor/prazo e aprova

No fim, abre o browser e pra cada aprovado:
1. Vai pra `/messages/bid/<slug>`
2. Preenche os 4 campos (Valor, Horas, Prazo, Detalhes)
3. Tenta selecionar os 3 destaques (via `featured_portfolio_ids`)
4. Para e te pede ENTER pra você revisar visualmente
5. Você confirma → clica "Continuar" → modal de confirmação → envia

## Estrutura

```
src/
├── browser/session.py    # Playwright persistent context
├── scraper/
│   ├── jobs_list.py      # Cards do feed
│   ├── job_detail.py     # Página da vaga
│   ├── job_insight.py    # Média de concorrentes
│   ├── profile.py        # Conexões disponíveis
│   └── bid_form.py       # Submissão da proposta
├── ai/
│   ├── prompts.py        # System instruction
│   └── generator.py      # Chamada ao DeepSeek (SDK openai)
├── db/
│   ├── schema.sql
│   └── tracker.py        # SQLite
├── filters/matcher.py    # Decide se vaga passa
├── utils/                # config, logger, delays
└── main.py               # CLI: scrape, list-drafts

approve.py                # Review interativo + envio
```

## Decisões de design que tomei

- **Login manual da primeira vez**: usa `launch_persistent_context` com `./data/chrome-profile`. Mais simples que CDP attach e mais confiável que login automático.
- **Semi-automático com ENTER manual antes do submit**: mesmo aprovado no `approve.py`, ele pausa com o form preenchido pra você dar uma última conferida antes do clique. Reduz risco de enviar coisa estranha enquanto a confiança ainda é baixa.
- **Bid form com 4 campos**: descobri lendo o HTML real do form que `bid[hours]` e `bid[deliveryTime]` existem além de `amount` e `content`. Preenchi todos pra cobrir tanto projeto fixo quanto por hora.
- **Featured portfolio configurável**: como o modal de portfólio é Vue.js e os mesmos 3 sempre fazem sentido, virou config (`featured_portfolio_ids` no profile.yaml).
- **DeepSeek V4 Flash por padrão**: barato e rápido. Se quiser propostas mais elaboradas, troca pra `deepseek-v4-pro` no `.env`.

## Pendências que precisam de você

- [ ] Preencher `DEEPSEEK_API_KEY` e `WORKANA_USER_ID` no `.env`
- [ ] Preencher `featured_portfolio_ids` no `config/profile.yaml`
- [ ] Revisar `config/profile.yaml` (links, skills, valores)
- [ ] Primeira execução: logar manualmente quando o browser abrir

## Troubleshooting

- **"Sessão não autenticada"** → loga manualmente no browser e dá ENTER no terminal.
- **Seletor não encontrado** → o Workana atualizou o HTML. Roda com `LOG_LEVEL=DEBUG` e me manda o erro + um print novo da página.
- **DeepSeek retorna JSON malformado** → temperatura muito alta ou prompt confuso; ajusta `_TEMPERATURE` em `src/ai/generator.py` ou o prompt em `src/ai/prompts.py`.
- **Modal de portfólio não abre** → o seletor `#portfolioOpenBidDialog` mudou; me manda o HTML atualizado do bid form.
