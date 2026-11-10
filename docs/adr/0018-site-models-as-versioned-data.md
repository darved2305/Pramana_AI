# 0018: Site models as versioned data; role and language catalogues; physics stays code

**Status:** proposed

**Amends:** 0004 (engine model: the engine compiles a stored spec instead of a file on disk) and
0001 (packs move from the `packs/` directory into the database; the domain package keeps the
validator).

**Context.** PRODUCTION.md §8. The only site is `packs/campus_block_c.yaml`, loaded by
`pramana_domain.load_pack`. Roles and languages are the `Role` and `TemplateLanguage` enums,
enforced by `pramana_domain/pack.py:344`. A hospital has nurses; Prisma supports more languages
than four.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Keep YAML files, one per customer, reviewed in git | Code review for every change | Customers cannot model their own building |
| Mutable model rows edited in place | Simple | Open investigations would change under the engine; replay breaks |
| **Immutable published versions; drafts autosave; investigations pin a version** | Replay stays exact; diffs and rollback are free; compiled models cache by content hash | More tables and a publish step |

**Decision.**
- `site_models(site_id, version, status, spec, spec_sha256, validation)`. A trigger forbids
  changing the spec of a published row. Investigations store `site_model_id`.
- The engine compiles from the stored spec and caches by `spec_sha256` (content-addressed, never
  invalidated).
- Data per organization: places, walks, components, failure modes, priors, probes chosen from the
  probe library with templates per language, actions, a role catalogue mapped to the three skill
  classes, a language catalogue, decision classes and losses.
- Code, reviewed and tested: domain physics (`pramana_domain/physics.py`), the engine, the probe
  library, the safety linter, the skill classes and the per-language speakable normalizer.
- Health check: the existing `pramana_eval` harness runs against a draft as a job (§8.6).
- `campus_block_c` becomes the "Hostel block" reference template and the sandbox model.

**Consequences.** New domains (water, HVAC, lifts) still need code. Model authoring cost is the
main product risk (PRODUCTION.md §18 item 5). Changing compile output changes beliefs, so any
change to compilation follows ADR 0003's `MODEL_VERSION` rule.

**Tests.** Publishing twice creates two versions and the first is unchanged; editing a published
row fails in the database; an open investigation keeps its pinned version after a new publish
(DA-08); compiling the stored `campus_block_c` spec gives the same `spec_sha256` and the same
S1, S2 and S7 outcomes as the file; the health check reproduces the benchmark on
`campus_block_c`.
