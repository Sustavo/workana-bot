"""Exceções tipadas pra controlar o fluxo de parada da automação.

Hierarquia:
- StopRun: algo grave aconteceu, ABORTE a run inteira (não adianta seguir).
    - AIFatalError: erro de API da IA/DeepSeek (quota/saldo/auth/indisponível) → abortar.
    - SuspiciousActivityError: Workana sinalizou bloqueio/captcha/atividade suspeita.
- SubmitVerificationError: erro POR-VAGA no envio do bid. NÃO é StopRun: o caller
  deve registrar a falha mas NÃO marcar o draft como 'sent', e seguir pra próxima.
- PauseAndResume: sinal interno de "pause e espere o usuário intervir" (captcha/login).
"""
from __future__ import annotations


class StopRun(Exception):
    """Base: aborte a automação inteira de forma limpa."""


class AIFatalError(StopRun):
    """Erro da API da IA (DeepSeek) que não adianta continuar agora: auth (401),
    saldo insuficiente (402), permissão (403) ou indisponibilidade persistente
    (429/5xx) que sobreviveu aos retries. → abortar a run."""


class SuspiciousActivityError(StopRun):
    """Workana sinalizou bloqueio/captcha/atividade suspeita — pare pra evitar ban."""

    def __init__(self, reason: str, url: str = "") -> None:
        self.reason = reason
        self.url = url
        super().__init__(f"{reason} (url={url})" if url else reason)


class PauseAndResume(Exception):
    """Sinal de 'pause e espere intervenção manual' (ex.: captcha/login).

    Diferente de StopRun: quem trata pode pedir ENTER ao usuário e continuar.
    Carrega a SuspiciousActivityError original pra contexto.
    """

    def __init__(self, reason: str, url: str = "") -> None:
        self.reason = reason
        self.url = url
        super().__init__(f"{reason} (url={url})" if url else reason)


class SubmitVerificationError(Exception):
    """submit() não conseguiu CONFIRMAR o envio do orçamento.

    kind ∈ {'below_min','no_redirect','validation','no_button','amount_drift','unknown'}.
    'amount_drift' = o valor do campo derivou (o Vue reescreveu) e não deu pra fixar.
    NÃO é StopRun: o caller trata como falha por-vaga (não marca 'sent').
    """

    def __init__(self, reason: str, kind: str = "unknown") -> None:
        self.reason = reason
        self.kind = kind
        super().__init__(reason)


class BidUnavailableError(Exception):
    """A página do bid não está disponível p/ esta vaga (ex.: 'Acesso Negado' —
    sem form#bidForm). NÃO é StopRun nem falha de envio: o caller deve PULAR a
    vaga (e, por decisão do usuário, descartar o rascunho) e seguir pra próxima.
    """

    def __init__(self, reason: str, url: str = "") -> None:
        self.reason = reason
        self.url = url
        super().__init__(f"{reason} (url={url})" if url else reason)
