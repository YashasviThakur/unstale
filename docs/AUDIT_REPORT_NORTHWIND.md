# Stale-belief report: Northwind Labs

Mon 22 Jun to Wed 1 Jul (9.4 days, 10 mornings replayed, 8 people and agents).

**5 of 8 people and agents worked from an outdated fact at some point**, for **57.9 stale person-days** in total. 9 of the 12 changes made in this period were missed by someone. Only 1 of the 14 outdated beliefs was corrected on its own; 13 were still held at the end.

## Changes that were missed, most costly first

| Change | Posted in | By | Old → new | Stale person-days | Who was behind |
|---|---|---|---|---|---|
| Team plan: price | #pricing | Lena Fischer | $39/seat/month → $49/seat/month | 19.1 | Maya Lopez, Tom Becker, Support agent |
| Payments service: owner | #eng-payments | Arjun Mehta | Arjun Mehta → Sara Kim | 9.4 | Tom Becker, Priya Raman |
| Payments API v1: status | #eng-payments | Sara Kim | supported → deprecated | 8.8 | Tom Becker, Support agent |
| Release 2.4: ship date | #release | Priya Raman | Mon 29 Jun → Fri 3 Jul | 5.4 | Maya Lopez |
| Release 2.4: code freeze | #release | Dev Patel | Fri 26 Jun → Wed 1 Jul | 5.4 | Maya Lopez |
| SSO: target release | #release | Priya Raman | 2.4 → 2.5 | 4.4 | Maya Lopez |
| Payments service: webhook retries | #eng-payments | Sara Kim | 3 → 5 | 2.4 | Arjun Mehta |
| Kestrel QBR: meeting time | email | Tom Becker | Tue 30 Jun, 10:00 UTC → Thu 2 Jul, 14:00 UTC | 2.4 | Maya Lopez |
| Monthly plan refunds: refund window | #pricing | Lena Fischer | 30 days → 14 days | 0.8 | Tom Becker, Support agent |

## Where changes leak out

| Posted in | Changes posted | Missed by someone | Leak rate | People who missed one | Stale person-days |
|---|---|---|---|---|---|
| #eng-payments | 3 | 3 | 100% | 4 | 20.6 |
| #pricing | 2 | 2 | 100% | 3 | 19.9 |
| #release | 6 | 3 | 50% | 1 | 15.2 |
| email | 1 | 1 | 100% | 1 | 2.4 |

## Who lags

| Person | Role | Stale person-days | Outdated beliefs | Still stale at the end | Longest |
|---|---|---|---|---|---|
| Maya Lopez | Account executive | 23.9 | 5 | 5 | 6.4 days |
| Tom Becker | Customer success manager | 15.1 | 4 | 3 | 6.4 days |
| Support agent | AI agent answering customer questions | 11.1 | 3 | 3 | 6.4 days |
| Priya Raman | Product manager | 5.4 | 1 | 1 | 5.4 days |
| Arjun Mehta | Payments engineering lead | 2.4 | 1 | 1 | 2.4 days |
| Sara Kim | Backend engineer | 0 | 0 | 0 | 0.0 days |
| Dev Patel | Site reliability engineer | 0 | 0 | 0 | 0.0 days |
| Lena Fischer | Revenue operations | 0 | 0 | 0 | 0.0 days |

A stale person-day is one person holding one outdated fact for one day, as the morning brief would have shown it (a fact is counted when Unstale is at least 50% sure). Estimated, not observed: Slack does not say who read a message, so each count carries the same confidence the brief does.
