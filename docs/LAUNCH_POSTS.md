# Unstale: launch posts

Ready to paste. Fill the two `<...>` links after the app is hosted and the walkthrough is recorded.
HydraDB's account is **@hydra_db** (X) and HydraDB on LinkedIn.

- Live app: `https://unstale.onrender.com`
- Walkthrough: `<VIDEO_LINK>`
- Repo: https://github.com/YashasviThakur/unstale

Screenshots are in docs/media (captured from the HydraDB build). Worth attaching: the graph view of a stale fact (click a fact chip, then the missing red edge) and the learning curve in the Proof panel.
Attach the 45 s ink-wash film or the 99 s features film to the first post (video gets more reach than
a link). Post the thread, then reply to a few teams who build agents or run RevOps.

---

## X / Twitter thread

**1/**
Your Slack search knows what's true. It has no idea who still believes the old thing.

Tom quoted the old price to a customer. The support bot gave out last month's refund window. Nobody
was careless; the change happened in a channel they weren't in.

I built Unstale for @hydra_db: it tells you who's working from an old version of the truth. 🧵

**2/**
How it works: one versioned graph on HydraDB.

- every fact keeps its history (new value retires the old one)
- every person or agent gets a SAW edge to each message they read

A person's stale beliefs are a graph traversal. Zero LLM tokens, about 80 ms.

**3/**
Slack never tells you who read what, so Unstale learns it.

Every "news to me" / "I knew this" click, every echo and restatement in a thread goes back into the
graph as read evidence. "Channel member" turns into a learned read rate.

On 40 orgs it had never seen, four sprints of evidence cut false alarms 22.2 → 15.9 per 100 briefs (95% interval for the change: −8.9 to −3.6).

**4/**
The test. 20 generated orgs, 5,210 messages, hidden per-person reading habits:

- Unstale: F1 0.75, 6.8 false alarms per 100 briefs
- daily changelog: precision 0.10, 105 false alarms
- vector RAG on the hand-labelled team: F1 0.13
- an LLM given every message and member list: F1 0.38

A plain store can't say "Tom saw v1, never saw v2".

**5/**
For agents: a support bot answering 31 customer questions got 29% right from its own knowledge base
and repeated an already-changed value 10 times. With Unstale's correction block (+116 tokens): 94%,
zero outdated answers. Works over MCP.

**5b/**
It doesn't stop at alerts. "Fix it" says who still needs to hear a change, which channel reaches them, who needs an @mention because they rarely read it, and drafts the message. Then it shows the corrections that would be left.

And the whole graph is a live MCP server: `claude mcp add --transport http unstale https://unstale.onrender.com/mcp`

**6/**
Runs on the open-source HydraDB engine in Docker, SelfGraph for versioned facts, Cypher for the
traversals. Slack export importer included.

Repo: https://github.com/YashasviThakur/unstale
Demo: `https://unstale.onrender.com`
Walkthrough: `<VIDEO_LINK>`

Built for the @hydra_db hackathon.

---

## LinkedIn

**Who in your company still believes the old price?**

Search and AI recaps tell you what is true now. They can't tell you who missed the change. That is
where the expensive mistakes live: the account exec quoting last week's ship date, customer success
renewing at the old price, a support bot repeating a refund policy that changed yesterday.

For the HydraDB hackathon I built Unstale. It keeps two things in one versioned graph: every fact with
its history, and who saw which version. The difference is a short list of exactly what each person or
agent is wrong about, why they missed it, and how sure we are. No LLM call is needed to compute it.

What it measured:
- 20 generated orgs with hidden reading habits: F1 0.75, 6.8 false alarms per 100 briefs. A daily
  changelog sends 105.
- It gets sharper as it learns: on 40 unseen orgs, false alarms fall 22.2 → 15.9 per 100 briefs after four sprints of feedback.
- A support agent: 29% correct on its own knowledge base, 94% with Unstale's correction block, with
  no outdated answers.

Built on the open-source HydraDB engine and SelfGraph. First buyers: Slack-first B2B teams where a
revenue team and a support agent sit downstream of product and pricing decisions. If that is you,
I'd like 15 minutes.

Repo: https://github.com/YashasviThakur/unstale
Live demo: `https://unstale.onrender.com`
Walkthrough: `<VIDEO_LINK>`

@HydraDB #HydraDB #AIAgents #RevOps

---

## Short version (Discord, Reddit, Hacker News "Show")

Unstale: who in your org still believes the old version of a fact? A versioned graph on open-source
HydraDB (facts with history + who-saw-which-version). Beats a daily changelog 6.8 vs 105 false alarms
per 100 briefs; a support bot goes from 29% to 94% correct with its correction block. Repo:
https://github.com/YashasviThakur/unstale


---

## Message for design partners (DM, email, community post)

Subject: do your reps and support bot work from last month's price?

Hi <name>, I built a tool that tells you who on your team (and which AI agents) are still working from an old version of a fact: a price, a ship date, a refund window. It reads who saw which message, not just what changed, so it doesn't send the "PSA" to people who were in the room. On a simulated company it cuts false alarms from 105 to 7 per 100 briefs against a daily changelog.

Could I run it on one exported Slack channel set of yours (or you try the demo, https://unstale.onrender.com) and tell you which three people were out of date last quarter? 15 minutes, and I'd like your honest read on whether you'd pay for it.
