# Unstale: go-to-market

**Search tells you what is true. Unstale tells you who doesn't know yet.**

## The problem, in money

Every company already pays for this. Grammarly and The Harris Poll estimate that poor communication
costs US businesses up to **$1.2 trillion a year, about $12,506 per employee**
([Business Wire, Jan 2022](https://www.businesswire.com/news/home/20220125005525/en/Grammarly-and-Harris-Poll-Research-Estimates-U.S.-Businesses-Lose-%241.2-Trillion-Annually-to-Poor-Communication)).
The expensive slice of that is narrow and recognisable:

- an account executive tells a customer the release ships Monday, after it moved to Friday in a channel
  she isn't in;
- customer success renews at the old price;
- a support agent tells a customer the refund window is 30 days, the day it became 14.

Each one is a person or an agent acting on a version of a fact that was already replaced. Nobody was
careless: the change happened somewhere they weren't looking. Today the only fix is a human who
notices and re-posts "PSA: pricing changed" in four channels, and still misses someone.

## Why now

AI agents now answer customers from knowledge bases, and every agent is one more reader who misses
changes. A stale person sends one wrong email; a stale agent gives the old refund policy to every
customer who asks that day. The cost of stale context used to be embarrassment. It is now a
volume problem. In our agent eval, a support agent answering from its own knowledge base repeated an
already-changed value in 10 of 31 answers; with Unstale's correction block (about 100 extra tokens),
in none.

## What exists, and the gap

| Category | Examples | What it answers | What it can't answer |
|---|---|---|---|
| Enterprise search | Glean | What documents mention X? | Which version did Tom see? |
| AI channel recaps | Slack AI | What happened in my channels? | Changes in channels you aren't in |
| Verified knowledge | Guru, Notion verified pages | Is this card still trusted? | Who read the old card |
| Authority-weighted retrieval | Unblocked | Which source wins right now? | Who acted on the loser |
| Temporal agent memory | Zep / Graphiti | When was this fact valid? | Which reader holds which version |
| **Unstale** | | **Who is working from an old version, why, and since when** | |

Everyone in the market solves *what is true now* (Unblocked's own roundup of the space puts it this
way: "staleness is a ranking problem"). None of them keep the second half of the record: **who saw
which version**. That half is what turns "the price changed" into "Tom and the support agent still
quote $39, and here is the message they got it from".

We measured the obvious alternative, a daily changelog of every change to things you own. On 20
generated orgs it scores precision 0.10 and sends **105 false alarms per 100 briefs**, because it
can't tell the people who were in the room from the people who weren't. Unstale sends **7**
([benchmark](../README.md#benchmark-20-generated-orgs-hidden-reading)).

## Who buys first

**Ideal first customer:** a Slack-first B2B SaaS company, 50 to 500 people, where product and pricing
decisions move fast and a revenue team (account executives, customer success, support) and at least
one AI support agent sit downstream of them.

- **Buyer:** VP of Revenue Operations or Head of Support Operations. They own what reps and bots tell
  customers, and they get the escalation when it's wrong.
- **Champion:** the RevOps or enablement lead who currently re-posts every change by hand.
- **Second buyer:** teams building agents, who need a context layer that says "these 3 things in your
  context changed" in 80 tokens instead of re-feeding the whole history.

## The wedge

Start where a wrong statement has a customer on the other end:

0. **Close the gap**, the part that makes it more than an alert: for any changed fact, who still needs to hear it, where to
   post, who needs an @mention, and a draft. This is what a RevOps lead does by hand today. A what-if shows the corrections
   that would be left.
1. **Check before sending** for customer-facing people: one click on a draft, and the two outdated
   facts in it are flagged with the message that changed them.
2. **Morning corrections** for the same people: the three things you believe that stopped being true,
   with confidence and a "news to me / I knew" button.
3. **A correction block for support agents**, through MCP, before every answer.

The pilot metric is concrete: **outdated statements caught before they reached a customer, per
week**, plus the share of corrections people mark "news to me" (precision, measured by the users
themselves).

## Product surface and distribution

| Surface | Status | Channel |
|---|---|---|
| Slack export import, one command | Built (`python -m unstale.slack_import`) | Self-serve trial on your own history |
| MCP server: `corrections`, `check_before_sending`, `who_believes`, `give_feedback` | Built | MCP registries, agent frameworks |
| Web desk (brief, team view, fact history, pre-send check, feedback) | Built | Demo and admin view |
| **Stale-belief report**: stale person-days, missed changes, leaky channels, who lags, as a page or Markdown (`/api/report.md`; sample: [AUDIT_REPORT_NORTHWIND.md](AUDIT_REPORT_NORTHWIND.md)) | Built | The audit deliverable: the sales call |
| Slack app: morning DM, message-action check, feedback buttons | Next | Slack Marketplace |
| Read receipts from Teams chats, email opens, agent context logs | Next | Sharpens exposure where it exists |

The deliverable of that import is the **stale-belief report** (see the Report button in the app, or the sample in
[AUDIT_REPORT_NORTHWIND.md](AUDIT_REPORT_NORTHWIND.md)). For the demo team it reads: 5 of 8 people and agents worked
from an outdated fact, 58 stale person-days in 9 days, 9 of the 12 changes missed by someone, 13 of the 14 outdated
beliefs never corrected, and every change posted in #pricing and #eng-payments missed by someone. That is what a RevOps
lead pays to see, before they pay for anything else. The pilot metric (outdated statements caught per week) is its
forward-looking half.

The import path matters for a trial: a RevOps lead can run Unstale on last quarter's export and see
"these 11 people were working from an old price on these dates" before anyone installs anything.
That report is the sales call.

## Pricing (hypothesis to test with design partners)

- **Free:** one team, up to 15 people and one agent.
- **Team:** $6 per person per month, priced like a Slack add-on, for briefs, pre-send checks and feedback learning.
- **Agents:** $20 per agent per month, for the MCP correction layer, with a volume of checks included and usage pricing above it.

**The first paid step is an audit, not a seat licence** (also a hypothesis): run Unstale on a team's last quarter of
Slack export and deliver the stale-belief report: who was working from which outdated price, date or policy, from
when, and where it came from. A flat fee for the report, credited against the first year if they switch it on. Then a
four-week pilot on live data, judged on one number agreed up front: outdated statements caught before they reached
a customer, with the users' own "news to me" rate as the precision check. If it catches none, the pilot is free.

The agent line is where usage scales: one company runs a handful of people per team but can run
dozens of agents, each checking before every answer.

## Why this compounds (the moat)

- **The exposure graph is the asset.** Who saw which version of which fact is not in any document; it
  is reconstructed from interactions and kept as edges in a versioned graph on HydraDB.
- **It gets sharper every run.** Each "news to me", each echo, each restatement is evidence about who
  reads which channel, written back to the graph. On a held-out sprint, false alarms fall from 11.1 to
  8.0 per 100 briefs as the graph accumulates two prior sprints of evidence, and the learned model
  matches a model given the true hidden read rates (F1 0.75 both). On 40 orgs it had never seen, four sprints of evidence cut false
  alarms 22.2 → 15.9 per 100 briefs (paired change −6.3, 95% interval −8.9 to −3.6).
- **Zero tokens per brief.** Briefs are graph traversals, not LLM calls, so cost doesn't grow with the
  number of people. LLM tokens are spent once per message, at extraction.

## Risks, and the answers

| Risk | Answer |
|---|---|
| "You're reading our Slack" | Runs on your infrastructure (HydraDB open source, self-hosted). The graph keeps claims and who-saw-what edges; message text is optional. |
| Notification fatigue | Precision is the product: 7 false alarms per 100 briefs against 105 for a changelog, and users' own feedback tunes it per person. |
| Exposure is guessed | It is estimated and shown with a confidence. Read receipts and agent context logs, where they exist, replace the guess. |
| Someone has to own the fact vocabulary | It starts from what the CRM and issue tracker already define (releases, plans, customers, owners); SelfGraph's ontology features grow it. |

## The next 90 days

1. Ship the Slack app with the morning DM and the message-action check.
2. Three design partners: import their last quarter, show the stale-belief report, run a four-week
   pilot measuring outdated statements caught.
3. Publish the generated-org benchmark as an open dataset so others can compete on it.
