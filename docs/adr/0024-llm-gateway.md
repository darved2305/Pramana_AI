# 0024: LLM gateway, paid providers, masking, evaluation gates

**Status:** proposed

**Amends:** 0007 (free-tier LLMs). Rules first and "the more cautious hedge wins" stay; free tiers
are not used with real participants' words.

**Context.** PRODUCTION.md §10. ADR 0007 chose Gemini and Groq free tiers as an optional second
opinion and notes that free-tier data may be used by the provider. Real people's words cannot be
sent on those terms.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Keep free tiers | No cost | Data terms forbid real personal data |
| Call providers directly from each feature | Quick | No shared budgets, masking, caching or kill switch |
| **One gateway module for every LLM call** | One place for timeouts, retries, masking, caching, budgets, prompt versions and tracing | We maintain it |
| A hosted gateway product | Features out of the box | Another party sees the text |

**Decision.**
- Extend `pramana_core/llm.py` into a gateway with per-role configuration (extractor, intake,
  explainer, site-model drafting): primary and fallback model, timeouts, at most one retry with
  jitter, and a kill switch.
- Paid providers with data-processing terms only, chosen by the extraction evaluations (for
  example a small fast model such as `claude-haiku-5-5`). Self-hosted Evon is the sovereign path
  when a customer requires processing in India (ADR 0012 remains a no-go for now).
- Mask names and phone numbers before sending; restore afterwards.
- Structured output only: the probe's outcomes plus `unknown`, validated by Pydantic.
- Exact cache in PostgreSQL keyed by a hash (never the text); no semantic cache.
- Every call records the prompt hash; budgets per organization and role; GenAI spans with prompt
  content off.

**Consequences.** Needs a paid key (R3 to R5). LLMs still decide nothing; the engine is unchanged,
so `MODEL_VERSION` is unaffected.

**Tests.** The existing extraction suites with "0 invented observations" as a hard gate; a masking
test that no name or phone number reaches the provider transport; the kill switch falls back to
rules; a cache hit stores no text.
