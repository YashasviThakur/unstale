# A real MCP session with Unstale

Endpoint: `https://unstale.onrender.com/mcp` (streamable HTTP, read-only on the public demo). Recorded with the official `mcp` Python client by `scripts/mcp_session.py`.

## tools/list

- `corrections`: List what `person` (e.g. 'agent:support-bot' or 'person:maya') believes that is no longer true.
- `who_to_notify`: For a changed fact (e.g. subject='plan:team', attribute='PRICED_AT'): who is still on the old value,
- `check_before_sending`: Check a draft against the current record before it is sent. Returns outdated facts and stale readers.
- `who_believes`: Show every version of one fact (e.g. subject='release:2.4', attribute='SHIPS_ON') and who holds which.
- `give_feedback`: Answer a correction for `person`: verdict 'news' (didn't know), 'knew', or 'neither' (never heard either value).

## corrections(person='person:maya', as_of='2026-06-29T08:00:00Z')

```
4 outdated beliefs for person:maya as of 2026-06-29T08:00:00Z:
- Team plan price: believes $39/seat/month, now $49/seat/month (changed 2026-06-25 by Lena Fischer in #pricing; 80% sure; slot plan:team|PRICED_AT). You're not in #pricing.
- Release 2.4 ship date: believes 2026-06-29, now 2026-07-03 (changed 2026-06-26 by Priya Raman in #release; 100% sure; slot release:2.4|SHIPS_ON). You're not in #release.
- SSO target release: believes 2.4, now 2.5 (changed 2026-06-27 by Priya Raman in #release; 100% sure; slot feature:sso|AVAILABLE_IN). You're not in #release.
- Release 2.4 code freeze: believes 2026-06-26, now 2026-07-01 (changed 2026-06-26 by Dev Patel in #release; 80% sure; slot release:2.4|CODE_FREEZE). You're not in #release.
```

## who_believes(subject='plan:team', attribute='PRICED_AT', as_of='2026-07-01T12:00:00Z')

```
Team plan: price
- $39/seat/month from 2026-06-22T10:00 (Lena Fischer, #sales)
- $49/seat/month from 2026-06-25T09:00 (Lena Fischer, #pricing) [current]
  Priya Raman: $49/seat/month
  Maya Lopez: $39/seat/month (STALE)
  Tom Becker: $39/seat/month (STALE)
  Lena Fischer: $49/seat/month
  Support agent: $39/seat/month (STALE)
```

## who_to_notify(subject='release:2.4', attribute='SHIPS_ON', as_of='2026-06-29T08:00:00Z')

```
Release 2.4: ship date is now 2026-07-03. Still on the old value: Maya Lopez (100%).
Plan:
- Post in #general (reaches Maya Lopez).
Expected still out of date after: 0.2 of 1.
Draft: Heads up: Release 2.4 ship date is now Fri 3 Jul (it was Mon 29 Jun). Changed Fri 26 Jun in #release by Priya Raman. If you were working from the old value, please update.
```

## corrections(person='agent:support-bot', as_of='2026-07-01T12:00:00Z')

```
3 outdated beliefs for agent:support-bot as of 2026-07-01T12:00:00Z:
- Team plan price: believes $39/seat/month, now $49/seat/month (changed 2026-06-25 by Lena Fischer in #pricing; 100% sure; slot plan:team|PRICED_AT). This agent doesn't read #pricing, so its context never got the change.
- Payments API v1 status: believes supported, now deprecated (changed 2026-06-27 by Sara Kim in #eng-payments; 100% sure; slot api:payments-v1|STATUS). This agent doesn't read #eng-payments, so its context never got the change.
- Monthly plan refunds refund window: believes 30 days, now 14 days (changed 2026-07-01 by Lena Fischer in #pricing; 100% sure; slot policy:monthly-refunds|WINDOW). This agent doesn't read #pricing, so its context never got the change.
```

## check_before_sending(author='person:maya', channel='sales', as_of='2026-06-29T08:55:00Z', text='Brightline is pumped. Told Jordan 2.4 goes live today and SSO is in it!')

```
OUTDATED: Release 2.4 ship date is 2026-07-03, not 2026-06-29 (changed 2026-06-26 in #release).
OUTDATED: SSO target release is 2.5, not 2.4 (changed 2026-06-27 in #release).
READER STALE: Tom Becker still thinks Release 2.4 ship date is 2026-06-29 (now 2026-07-03).
READER STALE: Tom Becker still thinks SSO target release is 2.4 (now 2.5).
READER STALE: Lena Fischer still thinks Release 2.4 ship date is 2026-06-29 (now 2026-07-03).
READER STALE: Lena Fischer still thinks SSO target release is 2.4 (now 2.5).
```
