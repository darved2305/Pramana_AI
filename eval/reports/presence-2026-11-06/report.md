# Benchmark report (generated; do not edit)

Commit `05637d9`, seeds 20000-20199, scenario mix {'single': 123, 'pair': 35, 'no_fault': 11, 'access_limited': 31}.
False-presence rate 0.30; scenarios with an adversary: 169.

| Policy | Success | Accuracy (decided) | Accuracy (identifiable) | False confidence | Abstention recall (unidentifiable) | Pair accuracy | Probes (mean) | Presence checks (mean) | Effort s (mean) | People | Time to conclusion s (mean) | Withdrawn (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E_ours | 77.5% | 93.0% | 67.7% | 2.5% | 71.4% | 65.7% | 6.43 | 0.85 | 206.08 | 2.62 | 206.08 | 0.00 |
| E-no_presence_challenges | 58.5% | 90.5% | 38.5% | 2.5% | 71.4% | 25.7% | 7.51 | 0.00 | 272.40 | 2.92 | 272.40 | 0.00 |

Paired differences, E minus each policy (bootstrap 95% CI):

- vs E-no_presence_challenges: success: +0.190 [+0.135, +0.245]; probes: -1.075 [-1.345, -0.815]; effort_s: -66.325 [-79.485, -53.705]; wall_s: -66.325 [-79.485, -53.705]
