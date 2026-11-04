# 0007: Free-tier LLMs: where they are used and how they are kept safe

**Status:** accepted

**Context.** There is no paid LLM budget. The free options were checked on 2026-11-04:
- **Gemini** (Google AI Studio): Flash models free. On the day, 3.8 Flash returned 503 "high
  demand", 2.5 Flash was not offered to new users, and 3.5 Flash and 3.1 Flash-Lite worked.
- **Groq:** `openai/gpt-oss-120b`, with 1,000 requests/day and 8,000 tokens/minute (from the
  response headers).
- **xAI Grok** has no free tier, and **Cerebras** requires a card.

**Decision.**
1. **The LLM never makes decisions.** The planner, stopping rule and verification are
   deterministic code.
2. **Answer extraction is rules first** (`language/hybrid.py`). An LLM (Gemini Flash-Lite) is
   asked only when the rules return "unknown", and never for injection attempts, stop requests,
   "can't see it", guesses or stale reports. Its output is schema-limited to the probe's
   outcomes plus "unknown". The more cautious hedge wins. Any failure falls back to the rules'
   answer. Interactive calls have an 8 s timeout and never wait more than 2 s for quota.
3. **The LLM-as-policy baseline** (benchmark policy B) runs on Groq and Gemini through one client
   (`pramana_core/llm.py`). The client:
   - paces itself under requests/minute, tokens/minute and a per-day counter, and follows
     Groq's live quota headers;
   - caches every response on disk, so re-runs and interrupted runs cost nothing;
   - pins one model per run and retries 429/5xx on that same model;
   - reports provider failures separately from the policy's choices.

**Measured.** On the 48-answer development set (`eval/data/extraction_set.jsonl`):
- rules only: 40/48 correct, 0 invented observations;
- rules + Gemini 3.1 Flash-Lite: 48/48, 0 invented.

This set was also used for development, so these figures are optimistic; a held-out set is
still needed.

**Consequences.** Free-tier data may be used by the provider, so only synthetic site data and
participant answers are sent, never personal data. The extractor works fully offline
(`LLM_EXTRACTOR_PROVIDER=none`, which is the default).
