# Benchmark report (generated; do not edit)

Commit `8c2607d-dirty`, seeds 10000-10299, scenario mix {'single': 206, 'pair': 39, 'no_fault': 15, 'access_limited': 40}.

| Policy | Success | Accuracy (decided) | Accuracy (identifiable) | False confidence | Abstention recall (unidentifiable) | Pair accuracy | Probes (mean) | Effort s (mean) | People | Time to conclusion s (mean) | Withdrawn (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E_ours | 84.7% | 92.9% | 79.0% | 1.7% | 67.9% | 79.5% | 5.50 | 189.15 | 2.52 | 189.15 | 0.00 |
| E-stricter | 81.0% | 94.7% | 73.2% | 1.7% | 69.6% | 76.9% | 5.50 | 189.15 | 2.52 | 189.15 | 0.00 |
| E-ask_more | 87.3% | 94.8% | 82.9% | 2.0% | 66.1% | 74.4% | 5.87 | 203.87 | 2.63 | 203.87 | 0.00 |

Paired differences, E minus each policy (bootstrap 95% CI):

- vs E-stricter: success: +0.037 [+0.013, +0.060]; probes: +0.000 [+0.000, +0.000]; effort_s: +0.000 [+0.000, +0.000]; wall_s: +0.000 [+0.000, +0.000]
- vs E-ask_more: success: -0.027 [-0.047, -0.010]; probes: -0.370 [-0.500, -0.263]; effort_s: -14.720 [-20.718, -9.887]; wall_s: -14.720 [-20.718, -9.887]
