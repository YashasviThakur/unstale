# Benchmark: 20 generated orgs x 3 sprints (Python twin, parity-checked against HydraDB)

5,210 messages, 229 people and agents, 5,496 briefs per method, threshold 0.5, 70% of corrections answered.

| Method | Precision | Recall | F1 | False alarms per 100 briefs |
|---|---|---|---|---|
| **Unstale (learned exposure)** | 0.87 | 0.66 | 0.75 | 6.8 |
| Unstale, learned from echoes only | 0.68 | 0.67 | 0.68 | 21.6 |
| Unstale v1 (every channel member read every message) | 0.68 | 0.67 | 0.67 | 21.4 |
| Interactions only | 0.49 | 0.55 | 0.52 | 39.3 |
| Daily changelog of changes in your scope | 0.10 | 0.16 | 0.12 | 105.5 |
| Same model with the true hidden read rates | 0.83 | 0.69 | 0.75 | 9.4 |

By sprint (F1):

| Method | Sprint 1 | Sprint 2 | Sprint 3 |
|---|---|---|---|
| **Unstale (learned exposure)** | 0.76 | 0.73 | 0.76 |
| Unstale v1 (every channel member read every message) | 0.69 | 0.65 | 0.68 |

The last sprint, scored again with evidence from only the first n sprints:

| Prior sprints of evidence | Precision | Recall | F1 | False alarms per 100 briefs |
|---|---|---|---|---|
| 0 | 0.86 | 0.65 | 0.74 | 11.1 |
| 1 | 0.87 | 0.64 | 0.74 | 9.5 |
| 2 | 0.89 | 0.65 | 0.76 | 8.0 |

Calibration of the learned model (every candidate it scored):

| Predicted chance stale | Candidates | Actually stale |
|---|---|---|
| 0.0-0.1 | 2663 | 0.11 |
| 0.1-0.2 | 1752 | 0.18 |
| 0.2-0.3 | 988 | 0.16 |
| 0.3-0.4 | 817 | 0.24 |
| 0.4-0.5 | 622 | 0.21 |
| 0.5-0.6 | 210 | 0.46 |
| 0.6-0.7 | 136 | 0.70 |
| 0.7-0.8 | 216 | 0.80 |
| 0.8-0.9 | 290 | 0.73 |
| 0.9-1.0 | 1981 | 0.95 |
