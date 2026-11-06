# Presence challenge benchmark notes

This is an exploratory logic-mode comparison of `E_ours` and
`E-no_presence_challenges` on the 200 seeded `campus_block_c` scenarios recorded in
`summary.json`. It uses the configured 0.30 chance that the simulated guard falsely claims to be
at a restricted or moved-to location. Both policies receive the same scenario seeds and generated
participant answers.

## Supported by this run

- The report compares the two named policies on this generated scenario set and this false-presence
  model.
- The reported outcomes, confidence, probe, effort and simulated time values are outputs of the
  benchmark harness for the listed seeds.

## Not supported by this run

- It does not measure Gnani, speech recognition, voice quality, or real-world latency.
- It does not estimate how often real participants misreport their location or how well this policy
  generalizes to other buildings, packs, or adversary strategies.
- It is a 200-scenario ablation run, not the larger preregistered benchmark or a comparison against
  the other baseline policies.
