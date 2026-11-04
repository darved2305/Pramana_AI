# Benchmark report (generated; do not edit)

Commit `aea1929`, seeds 10000-10299, scenario mix {'single': 206, 'pair': 39, 'no_fault': 15, 'access_limited': 40}.

| Policy | Success | Accuracy (decided) | Accuracy (identifiable) | False confidence | Abstention recall | Probes (mean) | Effort s (mean) | People |
|---|---|---|---|---|---|---|---|---|
| E_ours | 84.7% | 92.9% | 79.0% | 1.7% | 46.3% | 5.50 | 189.15 | 2.52 |
| A_checklist | 64.0% | 97.1% | 48.3% | 0.3% | 62.1% | 11.66 | 493.95 | 3.62 |
| C_random | 56.3% | 96.2% | 36.1% | 0.0% | 72.6% | 10.64 | 580.38 | 3.34 |
| D_greedy_entropy | 83.3% | 92.3% | 77.6% | 1.7% | 47.4% | 4.74 | 231.04 | 2.28 |
| E-no_decision_focus | 85.0% | 93.0% | 79.5% | 2.0% | 46.3% | 5.49 | 188.24 | 2.53 |
| E-no_cost | 84.3% | 92.8% | 79.0% | 1.7% | 48.4% | 4.74 | 235.97 | 2.28 |

Paired differences, E minus each policy (bootstrap 95% CI):

- vs A_checklist: success: +0.207 [+0.157, +0.260]; probes: -6.153 [-6.587, -5.723]; effort_s: -304.803 [-326.794, -282.447]
- vs C_random: success: +0.283 [+0.223, +0.343]; probes: -5.133 [-5.653, -4.617]; effort_s: -391.230 [-422.007, -361.027]
- vs D_greedy_entropy: success: +0.013 [-0.027, +0.053]; probes: +0.767 [+0.517, +1.027]; effort_s: -41.890 [-53.567, -29.993]
- vs E-no_decision_focus: success: -0.003 [-0.017, +0.010]; probes: +0.013 [-0.047, +0.077]; effort_s: +0.910 [-0.937, +2.813]
- vs E-no_cost: success: +0.003 [-0.033, +0.040]; probes: +0.767 [+0.507, +1.030]; effort_s: -46.820 [-59.084, -34.330]
