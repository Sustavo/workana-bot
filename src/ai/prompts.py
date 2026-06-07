SYSTEM_INSTRUCTION = """Você escreve propostas curtas, em português, para vagas no Workana,
em nome do freelancer descrito no perfil abaixo.

Regras inquebráveis:
- Cumprimente o cliente pelo nome quando estiver disponível na descrição da vaga.
- Tom direto, humano, sem clichês de IA (nada de "Estou animado!", "Espero que..." etc.).
- Máx. 5 frases.
- Termine convidando para uma conversa/reunião.
- NÃO use bullet points nem markdown. Texto corrido.
- NÃO mencione concorrentes nem orçamento numérico no corpo (isso vai num campo separado).
- Use o estilo dos EXEMPLOS abaixo como referência de tom e estrutura.

Você responderá APENAS com JSON no formato:
{
  "content": "texto da proposta",
  "amount_brl": <número em reais. Se o usuário fornecer "Target de preço", use esse valor exato; caso contrário, estime um valor justo dado o escopo e o perfil>,
  "delivery_time": "ex.: 5 dias",
  "hours_estimate": <número de horas estimadas, ou null se for projeto fixo>
}
"""


def build_user_prompt(job: dict, insight: dict | None, discount_pct: float = 0.15) -> str:
    avg_value = (insight or {}).get("avg_bid_value")
    avg_text = (insight or {}).get("avg_bid_text") or "desconhecida"

    target_line = ""
    if avg_value:
        target = round(float(avg_value) * (1 - discount_pct))
        target_line = f"\nTarget de preço (já calculado, USE EXATAMENTE): R$ {target}"

    return f"""## Vaga
Título: {job.get("title")}
Orçamento declarado pelo cliente: {job.get("budget_text")}
Skills exigidas: {", ".join(job.get("skills") or []) }
País do cliente: {job.get("client_country") or "?"}
Status: {job.get("proposals_status") or "?"}

## Concorrência
Média de bid: {avg_text}{target_line}

## Descrição da vaga
{job.get("description") or "(sem descrição)"}
"""
