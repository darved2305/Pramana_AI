# 0001 — One uv workspace, one package per ownership boundary

**Status:** accepted

**Context.** The engine must never see the simulator's hidden truth, and the two developers own
different components (PLAN.md §3, §24).

**Decision.** A uv workspace with these packages: `pramana-contracts` (Pydantic, the canonical
schemas), `pramana-domain` (pack and physics), `pramana-engine` (pure numpy), `pramana-sim`
(service holding the sealed truth), `pramana-core` (API and runtime), and `pramana-eval`.
Dependencies are declared per package. Import-linter contracts in `pyproject.toml` forbid
`pramana_engine`, `pramana_core`, `pramana_domain` and `pramana_contracts` from importing
`pramana_sim` or `pramana_eval`, and keep the engine free of web, database and provider code.

**Consequences.** Isolation is enforced by the dependency graph, by CI (`lint-imports`), and at
runtime: the core holds no oracle key. Physics lives once, in `pramana_domain`, and is shared by
both sides on purpose. Model mismatch is introduced by scenarios (several faults; later,
unmodelled faults and map drift), not by duplicated code.
