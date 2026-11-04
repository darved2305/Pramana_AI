# Gnani spike

PLAN.md names this file as the home of the Day-1 Gnani spike. The findings live in
[`docs/engineering/GNANI_INTEGRATION.md`](engineering/GNANI_INTEGRATION.md): what was verified
against the documentation, the package sources and live calls, the account limits, billing
granularity, and the usage guards that came out of it. The voice design is in
[`docs/engineering/VOICE_ARCHITECTURE.md`](engineering/VOICE_ARCHITECTURE.md).

Measured Gnani accuracy and latency figures are **not** in this repository and must not be added.
The Gnani EULA (§16) forbids publishing them, so they are kept privately by the team. Only
integration facts (header shapes, limits, error behaviour, billing rounding) are recorded here.

To repeat the live checks (this spends credits): `python scripts/gnani_live_check.py --out <a
directory outside the repo>`.
