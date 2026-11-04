# 0012: Self-hosted Evon: no-go this week

**Status:** accepted (decision due Nov 5 in PLAN.md §26; revisit only if a GPU is provided)

**Question.** Can we self-host Gnani Evon v3.3 with vLLM as the "sovereign" language-model
path (PLAN D23, N20)?

## Evidence (public sources, read 2026-11-04)

- **Model size.** The Hugging Face card `gnani/gnani-evon-v3.3-30b-a3b` describes a 30B-total,
  roughly 3.5B-active hybrid Mamba2/Transformer mixture of experts (`nemotron_h`) in BF16,
  served with `vllm>=0.12.0`. BF16 weights for 30B parameters are about 60 GB before the KV
  cache, so it needs an 80 GB card. The card lists H100 80GB, H200 or A100 hardware and gives no
  minimum-VRAM or throughput figures.
  Sources: https://huggingface.co/gnani/gnani-evon-v3.3-30b-a3b,
  https://hackernoon.com/a-beginners-guide-to-gnani-evon-v33-benchmarks-use-cases-and-limitations
- **Indicative price in India.** E2E Networks lists A100 80GB at about Rs 220/hour on demand
  and H100 at about Rs 362/hour, before 18% GST. These are published list prices, not a quote.
  Sources: https://e2enetworks.com/blog/nvidia-a100-price-india,
  https://www.e2enetworks.com/gpus/nvidia-h100.md
- **Hosted alternative.** Friendli lists the model as a hosted endpoint
  (https://friendli.ai/models/gnani/gnani-evon-v3.3-30B-A3B). It needs an account and a
  payment method.
- **Budget.** The project has no paid LLM budget (ADR 0007). No GPU, card or provider account
  is available to the team.

## Decision

**No-go.** We could not obtain a quote or a GPU: both need a payment method we do not have.
Language roles stay on rules first with the free-tier hosted second opinion (ADR 0007). The
extractor is provider-agnostic (`LlmClient`, OpenAI-compatible), so an Evon vLLM endpoint can
be added through configuration later without code changes to the roles.

## What would change this

A GPU with at least 80 GB for about 4 hours (roughly Rs 900 to 1,500 at the list prices above),
or hosted Evon credits from Gnani. Then run N20: JSON-schema extraction accuracy on
`eval/data/extraction_heldout.jsonl` of at least 95% at p95 latency of 1.2 s or less.
