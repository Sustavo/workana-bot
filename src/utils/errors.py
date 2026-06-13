"""Exceções tipadas pra controlar o fluxo de parada da automação.

Hierarquia:
- StopRun: algo grave aconteceu, ABORTE a run inteira (não adianta seguir).
    - GeminiFatalError: erro de API do Gemini (quota/auth/indisponível) → abortar.
    - SuspiciousActivityError: Workana sinalizou bloqueio/captcha/atividade suspeita.
- SubmitVerificationError: erro POR-VAGA no envio do bid. NÃO é StopRun: o caller
  deve registrar a falha mas NÃO marcar o draft como 'sent', e seguir pra próxima.
- PauseAndResume: sinal interno de "pause e espere o usuário intervir" (captcha/login).
"""
from __future__ import annotations


class StopRun(Exception):
    """Base: aborte a automação inteira de forma limpa."""


class GeminiFatalError(StopRun):
    """Erro da API do Gemini que não adianta continuar (quota/429, auth, indisponível)."""


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

    kind ∈ {'below_min','no_redirect','validation','no_button','unknown'}.
    NÃO é StopRun: o caller trata como falha por-vaga (não marca 'sent').
    """

    def __init__(self, reason: str, kind: str = "unknown") -> None:
        self.reason = reason
        self.kind = kind
        super().__init__(reason)
