# Unstale: submission text

**Track:** 2, the context layer for agents.

**Tagline:** Find who's working from an old version of the truth.

## Short description (paste-ready)

Search, recaps and agent memory tell you what is true now. Unstale tells you who still believes the
old version. It keeps two things in one versioned graph on HydraDB: every fact with its history
(SelfGraph supersede), and who saw which version (a SAW edge from each person or agent to each message
they read). The difference is a short list of exactly what each person or agent is wrong about, why
they missed it, and how sure Unstale is, computed as a graph traversal with zero LLM tokens.

Slack doesn't say who read a message, so Unstale learns it: every "news to me / I knew this" on a
correction, and every echo or restatement people post, is written back to the graph as read evidence,
and turns "channel member" into a learned read rate. The graph gets sharper every run.

It ships as a corrections brief, a **Fix it** plan (who still needs to hear a change, which channel reaches them, who needs an
@mention, a draft, and a what-if of the corrections that would be left), a check-before-sending for drafts, a correction block for
agents, a **live MCP server** any agent can connect to (`claude mcp add --transport http unstale https://unstale.onrender.com/mcp`),
and a Slack export importer. Each fact's **Graph view** sits next to what a real vector search returns for the same question: the store
finds the right messages and cannot say who read which. People can also tell Unstale about facts it only *assumed* they had read, which
is how recall improves.

## Results

- **Hand-written team with exact answer key:** precision 1.00, recall 0.92, 0 tokens per brief. The
  best LLM baseline (every message plus every member list) reaches F1 0.38 at 3,188 tokens per brief;
  vector RAG 0.13.
- **20 generated orgs, 5,210 messages, hidden reading:** learned exposure F1 0.75 vs 0.67 for the
  original engine, false alarms down 68% (6.8 per 100 briefs), matching a model given the true hidden
  read rates. A daily changelog sends 105 false alarms per 100 briefs.
- **Sharper every run:** on the same held-out sprint, false alarms fall 11.1 → 9.5 → 8.0 per 100 briefs
  with 0, 1 and 2 prior sprints of evidence.
- **Unseen orgs:** on 40 more generated orgs it had never seen, four sprints of evidence cut false alarms from 22.2 to 15.9 per 100 briefs
  (paired change −6.3, 95% interval −8.9 to −3.6; 30 of 40 orgs improved). Control: the same number of answers with
  coin-flip verdicts doesn't improve (59.5 → 57.7, change not significant), so the learning comes from what people say.
- **Stale days removed vs noise:** acting on Unstale's default briefs removes 72% of stale person-days at 6.8 false alarms per
  100 briefs (84% at 27 on the most sensitive setting); the v1 engine removes the same 72% at 21.4; a daily changelog removes 95%
  at 105.5. A **stale-belief report** (stale person-days, missed changes, leaky channels, who lags) is the audit deliverable
  for the pilot (Report button in the app, `/api/report.md`, MCP tool `stale_report`).
- **Messy wording:** every message rewritten casually, tersely and rambling (the facts kept), extractor unchanged. Claim F1 0.94 to
  0.95 (1.00 as written); the corrections keep precision 1.00 and lose recall only on terse and casual text (0.92 to 0.78 and 0.71).
  Published as a limit, with the script (`scripts/robustness.py`, `scripts/robustness_e2e.py`).
- **Under load:** 20 concurrent users for 60 s on HydraDB 0.4.0, writing feedback to the graph while serving:
  3,546 requests, 0 errors, p50 208 ms, p95 1.0 s (`scripts/loadtest.py`, `eval/load.json`).
- **Would it fall apart on a plain store?** Yes: remove the who-saw-which-version edges and what is left is a
  changelog (F1 0.12, 105 false alarms per 100 briefs); a vector store over the same messages scores F1 0.13.
- **Agents:** a support agent answering 31 customer questions gets 29% right from its own knowledge base and 94% with Unstale's correction block (+116 tokens, 0 outdated answers). Dumping every message gets 90% at 5.8x the tokens; vector RAG over every message gets 97% but needs the bot to index every internal channel.
- **HydraDB:** the benchmark runs on HydraDB, and a pure-Python twin agrees with it brief for brief
  (168 of 168 briefs identical on 0.3.0; 308 of 308 on 0.4.0).

## How it uses HydraDB

HydraDB open-source engine (v0.4.0, Docker) holds the whole graph: people, channels, messages,
claims, SAW edges with strength, versioned fact relations and ReadEvidence nodes. SelfGraph caps each
fact attribute at one current value per subject (`max_count: 1`, `contradiction="supersede"`), so a
new statement retires the old one and keeps the history; `as_of` reads give time travel. Raw Cypher
does the belief traversals.

## Why it earns its place over a vector store

A vector store finds messages about "pricing". It can't represent "Tom saw version 1 of the price in
#sales and never saw version 2 in #pricing", so it can't tell Tom from Lena, who made the change. On
our labelled team, vector RAG scores F1 0.13.

## Links

- **Live app, on real open-source HydraDB 0.4.0:** https://unstale.onrender.com (landing page; the app itself is https://unstale.onrender.com/app) (free instance: the first visit after a quiet spell can take up to a minute to wake)
- **Live app, instant copy:** https://unstale.vercel.app (always up; runs the same engine on SelfGraph's embedded Kuzu store because Vercel can't run a HydraDB server, and says so in its top bar; Northwind scores precision 1.00 / recall 0.917 on both)
- **Run it yourself, real HydraDB, one command:** `docker build -t unstale . && docker run --rm -p 7860:7860 unstale`
- Repo: https://github.com/YashasviThakur/unstale
- Demo video: (add after recording)
- Go-to-market: docs/GTM.md, docs/LAUNCH_POSTS.md
