# Benchmark report (generated; do not edit)

Commit `56382dc`, seeds 40000-40299, scenario mix {'single': 197, 'pair': 40, 'no_fault': 16, 'access_limited': 47}.

| Policy | Completed episodes | Excluded failed runs | Historical success | Honest success | Accuracy (decided) | Accuracy (identifiable) | False confidence | Abstention recall (unidentifiable) | Historical precision | Justified P/R | Pair accuracy | Diagnostic probes (mean) | Diagnostic effort s (mean) | People | Time to conclusion s (mean) | Withdrawn (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E_ours | 300 | 0 | 83.3% | 80.3% | 92.0% | 76.7% | 2.0% | 67.2% | 62.1% | 51.7% / 67.2% | 72.5% | 5.76 | 197.81 | 2.52 | 197.81 | 0.00 |
| A_checklist | 300 | 0 | 63.0% | 57.7% | 94.5% | 44.6% | 2.0% | 77.6% | 39.5% | 30.2% / 77.6% | 55.0% | 11.62 | 492.75 | 3.59 | 492.75 | 0.00 |
| C_random | 300 | 0 | 60.7% | 50.3% | 89.9% | 39.9% | 1.3% | 79.1% | 44.0% | 27.7% / 79.1% | 22.5% | 10.47 | 562.63 | 3.24 | 562.63 | 0.00 |
| D_greedy_entropy | 300 | 0 | 84.7% | 82.0% | 93.5% | 77.7% | 2.3% | 67.2% | 62.4% | 52.9% / 67.2% | 75.0% | 4.90 | 243.04 | 2.32 | 243.04 | 0.00 |
| E_parallel3 | 300 | 0 | 83.0% | 78.3% | 94.5% | 75.1% | 2.3% | 68.7% | 60.0% | 46.0% / 68.7% | 62.5% | 7.81 | 290.86 | 3.25 | 124.34 | 0.57 |

Calibration and false-confidence counts by policy:

| Policy | Bin | Count / decided n | Mean confidence | Accuracy |
|---|---:|---:|---:|---:|
| E_ours | 1 | 0 / 213 | - | - |
| E_ours | 2 | 0 / 213 | - | - |
| E_ours | 3 | 0 / 213 | - | - |
| E_ours | 4 | 0 / 213 | - | - |
| E_ours | 5 | 0 / 213 | - | - |
| E_ours | 6 | 0 / 213 | - | - |
| E_ours | 7 | 0 / 213 | - | - |
| E_ours | 8 | 0 / 213 | - | - |
| E_ours | 9 | 59 / 213 | 85.2% | 81.4% |
| E_ours | 10 | 154 / 213 | 94.9% | 96.1% |
| A_checklist | 1 | 0 / 128 | - | - |
| A_checklist | 2 | 0 / 128 | - | - |
| A_checklist | 3 | 0 / 128 | - | - |
| A_checklist | 4 | 0 / 128 | - | - |
| A_checklist | 5 | 0 / 128 | - | - |
| A_checklist | 6 | 0 / 128 | - | - |
| A_checklist | 7 | 0 / 128 | - | - |
| A_checklist | 8 | 0 / 128 | - | - |
| A_checklist | 9 | 12 / 128 | 86.3% | 91.7% |
| A_checklist | 10 | 116 / 128 | 96.6% | 94.8% |
| C_random | 1 | 0 / 109 | - | - |
| C_random | 2 | 0 / 109 | - | - |
| C_random | 3 | 0 / 109 | - | - |
| C_random | 4 | 0 / 109 | - | - |
| C_random | 5 | 0 / 109 | - | - |
| C_random | 6 | 0 / 109 | - | - |
| C_random | 7 | 0 / 109 | - | - |
| C_random | 8 | 0 / 109 | - | - |
| C_random | 9 | 37 / 109 | 85.8% | 81.1% |
| C_random | 10 | 72 / 109 | 94.6% | 94.4% |
| D_greedy_entropy | 1 | 0 / 215 | - | - |
| D_greedy_entropy | 2 | 0 / 215 | - | - |
| D_greedy_entropy | 3 | 0 / 215 | - | - |
| D_greedy_entropy | 4 | 0 / 215 | - | - |
| D_greedy_entropy | 5 | 0 / 215 | - | - |
| D_greedy_entropy | 6 | 0 / 215 | - | - |
| D_greedy_entropy | 7 | 0 / 215 | - | - |
| D_greedy_entropy | 8 | 0 / 215 | - | - |
| D_greedy_entropy | 9 | 63 / 215 | 85.8% | 88.9% |
| D_greedy_entropy | 10 | 152 / 215 | 94.7% | 95.4% |
| E_parallel3 | 1 | 0 / 200 | - | - |
| E_parallel3 | 2 | 0 / 200 | - | - |
| E_parallel3 | 3 | 0 / 200 | - | - |
| E_parallel3 | 4 | 0 / 200 | - | - |
| E_parallel3 | 5 | 0 / 200 | - | - |
| E_parallel3 | 6 | 0 / 200 | - | - |
| E_parallel3 | 7 | 0 / 200 | - | - |
| E_parallel3 | 8 | 0 / 200 | - | - |
| E_parallel3 | 9 | 26 / 200 | 85.7% | 84.6% |
| E_parallel3 | 10 | 174 / 200 | 96.4% | 96.0% |

False-confidence and abstention by scenario stratum:

| Policy | Stratum | n | False confidence (count / rate) | Abstained | Justified abstentions | Unknown identifiability abstentions |
|---|---|---:|---:|---:|---:|---:|
| E_ours | single | 197 | 4 / 2.0% | 31 | 8 | 0 |
| E_ours | pair | 40 | 1 / 2.5% | 9 | 0 | 9 |
| E_ours | no_fault | 16 | 1 / 6.2% | 10 | 0 | 0 |
| E_ours | access_limited | 47 | 0 / 0.0% | 37 | 37 | 0 |
| A_checklist | single | 197 | 3 / 1.5% | 100 | 12 | 0 |
| A_checklist | pair | 40 | 2 / 5.0% | 16 | 0 | 16 |
| A_checklist | no_fault | 16 | 0 / 0.0% | 16 | 0 | 0 |
| A_checklist | access_limited | 47 | 1 / 2.1% | 40 | 40 | 0 |
| C_random | single | 197 | 3 / 1.5% | 106 | 13 | 0 |
| C_random | pair | 40 | 0 / 0.0% | 31 | 0 | 31 |
| C_random | no_fault | 16 | 1 / 6.2% | 14 | 0 | 0 |
| C_random | access_limited | 47 | 0 / 0.0% | 40 | 40 | 0 |
| D_greedy_entropy | single | 197 | 4 / 2.0% | 31 | 8 | 0 |
| D_greedy_entropy | pair | 40 | 1 / 2.5% | 8 | 0 | 8 |
| D_greedy_entropy | no_fault | 16 | 2 / 12.5% | 9 | 0 | 0 |
| D_greedy_entropy | access_limited | 47 | 0 / 0.0% | 37 | 37 | 0 |
| E_parallel3 | single | 197 | 5 / 2.5% | 39 | 9 | 0 |
| E_parallel3 | pair | 40 | 1 / 2.5% | 14 | 0 | 14 |
| E_parallel3 | no_fault | 16 | 1 / 6.2% | 10 | 0 | 0 |
| E_parallel3 | access_limited | 47 | 0 / 0.0% | 37 | 37 | 0 |

Pair and abstention outcomes (historical success above retains its original definition):

| Policy | Pair episodes | First useful action | Full pair resolution | Resolution n | Mean repairs | Verification probes | Justified abstentions | Abstentions with unknown identifiability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E_ours | 40 | 72.5% | 7.5% | 40 | 0.25 | 0.60 | 45 | 9 |
| A_checklist | 40 | 40.0% | 2.5% | 40 | 0.15 | 0.42 | 52 | 16 |
| C_random | 40 | 22.5% | 0.0% | 40 | 0.05 | 0.25 | 53 | 31 |
| D_greedy_entropy | 40 | 75.0% | 7.5% | 40 | 0.30 | 0.70 | 45 | 8 |
| E_parallel3 | 40 | 57.5% | 2.5% | 40 | 0.15 | 0.23 | 46 | 14 |

Paired differences, E minus each policy (bootstrap 95% CI):

- vs A_checklist: success: +0.203 [+0.153, +0.253]; honest_success: +0.227 [+0.173, +0.280]; probes: -5.857 [-6.287, -5.433]; effort_s: -294.940 [-318.407, -272.453]; wall_s: -294.940 [-318.407, -272.453]
- vs C_random: success: +0.227 [+0.170, +0.283]; honest_success: +0.300 [+0.240, +0.360]; probes: -4.707 [-5.220, -4.177]; effort_s: -364.823 [-395.751, -333.613]; wall_s: -364.823 [-395.751, -333.613]
- vs D_greedy_entropy: success: -0.013 [-0.050, +0.023]; honest_success: -0.017 [-0.057, +0.023]; probes: +0.860 [+0.593, +1.123]; effort_s: -45.233 [-58.761, -32.520]; wall_s: -45.233 [-58.761, -32.520]
- vs E_parallel3: success: +0.003 [-0.030, +0.037]; honest_success: +0.020 [-0.013, +0.057]; probes: -2.053 [-2.313, -1.793]; effort_s: -93.050 [-104.654, -81.743]; wall_s: +73.467 [+64.310, +82.987]

Registered paired tests (Holm across five comparisons per outcome):
Success definition: correct decision or abstention where identifiability is false; pair abstention is not success.

| Outcome | Comparison | Paired n | p | Holm p |
|---|---|---|---|---|
| success | E vs A_checklist | 300 | 1.72924e-15 | 6.91696e-15 |
| success | E vs B_llm | 0 | - | - |
| success | E vs C_random | 300 | 2.26252e-19 | 1.13126e-18 |
| success | E vs D_greedy_entropy | 300 | 0.522397 | 1 |
| success | E vs E_parallel3 | 300 | 0.361595 | 1 |
| probes | E vs A_checklist | 300 | 1.46818e-49 | 7.34089e-49 |
| probes | E vs B_llm | 0 | - | - |
| probes | E vs C_random | 300 | 1.66514e-38 | 6.66056e-38 |
| probes | E vs D_greedy_entropy | 300 | 4.75357e-12 | 9.50714e-12 |
| probes | E vs E_parallel3 | 300 | 1.54863e-35 | 4.64588e-35 |
| effort_s | E vs A_checklist | 300 | 1.43803e-50 | 7.19016e-50 |
| effort_s | E vs B_llm | 0 | - | - |
| effort_s | E vs C_random | 300 | 1.53253e-49 | 6.13011e-49 |
| effort_s | E vs D_greedy_entropy | 300 | 7.22868e-13 | 1.44574e-12 |
| effort_s | E vs E_parallel3 | 300 | 3.06103e-40 | 9.18309e-40 |

Matched-budget curves (SVG files alongside this report):

- questions: 40 policy-budget estimates with scenario bootstrap intervals
- effort_s: 68 policy-budget estimates with scenario bootstrap intervals
