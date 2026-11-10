# Benchmark report (generated; do not edit)

Commit `dbcc64c`, seeds 60000-60299, scenario mix {'single': 202, 'pair': 42, 'no_fault': 17, 'access_limited': 39}.

| Policy | Completed episodes | Excluded failed runs | Historical success | Honest success | Accuracy (decided) | Accuracy (identifiable) | False confidence | Abstention recall (unidentifiable) | Historical precision | Justified P/R | Pair accuracy | Diagnostic probes (mean) | Diagnostic effort s (mean) | People | Time to conclusion s (mean) | Withdrawn (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E_ours | 300 | 0 | 78.7% | 76.3% | 89.6% | 70.1% | 1.7% | 75.0% | 56.1% | 49.0% / 75.0% | 73.8% | 5.96 | 205.29 | 2.59 | 205.29 | 0.00 |
| D_greedy_entropy | 300 | 0 | 81.0% | 79.3% | 92.8% | 74.2% | 2.3% | 71.9% | 54.8% | 49.5% / 71.9% | 76.2% | 5.01 | 253.05 | 2.33 | 253.05 | 0.00 |

Calibration and false-confidence counts by policy:

| Policy | Bin | Count / decided n | Mean confidence | Accuracy |
|---|---:|---:|---:|---:|
| E_ours | 1 | 0 / 202 | - | - |
| E_ours | 2 | 0 / 202 | - | - |
| E_ours | 3 | 0 / 202 | - | - |
| E_ours | 4 | 0 / 202 | - | - |
| E_ours | 5 | 0 / 202 | - | - |
| E_ours | 6 | 0 / 202 | - | - |
| E_ours | 7 | 0 / 202 | - | - |
| E_ours | 8 | 0 / 202 | - | - |
| E_ours | 9 | 64 / 202 | 85.6% | 75.0% |
| E_ours | 10 | 138 / 202 | 94.3% | 96.4% |
| D_greedy_entropy | 1 | 0 / 207 | - | - |
| D_greedy_entropy | 2 | 0 / 207 | - | - |
| D_greedy_entropy | 3 | 0 / 207 | - | - |
| D_greedy_entropy | 4 | 0 / 207 | - | - |
| D_greedy_entropy | 5 | 0 / 207 | - | - |
| D_greedy_entropy | 6 | 0 / 207 | - | - |
| D_greedy_entropy | 7 | 0 / 207 | - | - |
| D_greedy_entropy | 8 | 0 / 207 | - | - |
| D_greedy_entropy | 9 | 62 / 207 | 85.8% | 87.1% |
| D_greedy_entropy | 10 | 145 / 207 | 94.5% | 95.2% |

False-confidence and abstention by scenario stratum:

| Policy | Stratum | n | False confidence (count / rate) | Abstained | Justified abstentions | Unknown identifiability abstentions |
|---|---|---:|---:|---:|---:|---:|
| E_ours | single | 202 | 4 / 2.0% | 46 | 12 | 0 |
| E_ours | pair | 42 | 1 / 2.4% | 7 | 0 | 7 |
| E_ours | no_fault | 17 | 0 / 0.0% | 10 | 1 | 0 |
| E_ours | access_limited | 39 | 0 / 0.0% | 35 | 35 | 0 |
| D_greedy_entropy | single | 202 | 5 / 2.5% | 44 | 11 | 0 |
| D_greedy_entropy | pair | 42 | 2 / 4.8% | 5 | 0 | 5 |
| D_greedy_entropy | no_fault | 17 | 0 / 0.0% | 10 | 1 | 0 |
| D_greedy_entropy | access_limited | 39 | 0 / 0.0% | 34 | 34 | 0 |

Pair and abstention outcomes (historical success above retains its original definition):

| Policy | Pair episodes | First useful action | Full pair resolution | Resolution n | Mean repairs | Verification probes | Justified abstentions | Abstentions with unknown identifiability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E_ours | 42 | 66.7% | 0.0% | 42 | 0.17 | 0.14 | 48 | 7 |
| D_greedy_entropy | 42 | 76.2% | 0.0% | 42 | 0.12 | 0.17 | 46 | 5 |

Paired differences, E minus each policy (bootstrap 95% CI):

- vs D_greedy_entropy: success: -0.023 [-0.067, +0.020]; honest_success: -0.030 [-0.073, +0.013]; probes: +0.950 [+0.660, +1.257]; effort_s: -47.757 [-61.350, -33.976]; wall_s: -47.757 [-61.350, -33.976]

Registered paired tests (Holm across five comparisons per outcome):
Success definition: correct decision or abstention where identifiability is false; pair abstention is not success.

| Outcome | Comparison | Paired n | p | Holm p |
|---|---|---|---|---|
| success | E vs A_checklist | 0 | - | - |
| success | E vs B_llm | 0 | - | - |
| success | E vs C_random | 0 | - | - |
| success | E vs D_greedy_entropy | 300 | 0.222053 | 1 |
| success | E vs E_parallel3 | 0 | - | - |
| probes | E vs A_checklist | 0 | - | - |
| probes | E vs B_llm | 0 | - | - |
| probes | E vs C_random | 0 | - | - |
| probes | E vs D_greedy_entropy | 300 | 1.49143e-10 | 7.45717e-10 |
| probes | E vs E_parallel3 | 0 | - | - |
| effort_s | E vs A_checklist | 0 | - | - |
| effort_s | E vs B_llm | 0 | - | - |
| effort_s | E vs C_random | 0 | - | - |
| effort_s | E vs D_greedy_entropy | 300 | 4.21205e-12 | 2.10602e-11 |
| effort_s | E vs E_parallel3 | 0 | - | - |
