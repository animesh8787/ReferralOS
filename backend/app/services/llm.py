"""Pluggable LLM interface. The default is NoLLM: every feature works deterministically without any model.

An LLM may only PROPOSE a rewording of one existing bullet. The proposal is accepted only if it passes
tailoring.validate.check_rewrite (no new technologies, no new numbers, no new proper nouns); otherwise the original stands.
LLM output is never trusted as fact.
shortcut: no hosted-provider client yet; a provider needs the per-user key store, consent and budget cap from Phase 10.
"""
from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def rewrite_bullet(self, bullet: str, jd_terms: list[str]) -> str | None: ...


class NoLLM:
    name = "none"

    def rewrite_bullet(self, bullet: str, jd_terms: list[str]) -> str | None:
        return None


def get_provider() -> LLMProvider:
    return NoLLM()
