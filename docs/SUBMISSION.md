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

It ships as a corrections brief, a check-before-sending for drafts, a correction block for agents
over MCP, and a Slack export importer.

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
  (paired change −6.3, 95% interval −8.9 to −3.6; 30 of 40 orgs improved).
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

- Live app: https://unstale.vercel.app (hosted on SelfGraph's embedded Kuzu store, because Vercel can't run a HydraDB server; same engine code and queries, Northwind scores precision 1.00 / recall 0.917 on both. The HydraDB build is the one in `infra/docker-compose.yml`.)
- Repo: https://github.com/YashasviThakur/unstale
- Demo video: (add after recording)
- Go-to-market: docs/GTM.md
