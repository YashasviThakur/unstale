# Demo video script (about 2 min 50 s)

Setup before recording: Docker running, `docker compose --env-file .env up -d` in `infra/`,
then **a fresh ingest** (`python scripts/ingest.py`, about 30 s, cached LLM replies) so no earlier
feedback clicks are in the graph. Then `uvicorn unstale.api:app --port 8765`, browser at
http://localhost:8765, window about 1440 x 900. The page opens on Mon 29 Jun, 08:00, viewing as Maya.
Have `docs/bench-twin.svg` and `eval/AGENT.md` open in tabs for section 6.

## 0. Ink-wash opener (optional, replaces section 1)

The film `D:\unstale-film\renders\unstale-ink-wash-handscroll.mp4` (45.5 s) tells the same story as the
demo, painted: the date changes in #release, the news never reaches Maya, and the Unstale seal stops her
message. Cuts that drop into the video:

- `unstale-film-opener.mp4` (0:00 to 0:29.6): the problem and the catch. Its captions carry the story, so
  narrate lightly or not at all, then cut to the real UI for section 2.
- `unstale-film-endcard.mp4` (0:38.0 to 0:45.5): the "Unstale" title and seal, for the last shot.

## 1. The problem (0:00 to 0:20)

Screen: the Messages tab, scrolled to Fri 26 Jun.

> A deadline moves in a thread half the team wasn't in. A price changes in a channel sales doesn't
> read. Search can tell you what's true now. Nothing tells you who still believes the old version.
> That's what Unstale does.

## 2. Maya's morning (0:20 to 0:50)

Screen: the Corrections panel on the right.

> It's Monday morning. Maya, our account exec, believes four things that are no longer true.
> 2.4 was supposed to ship today. It moved to Friday, in a #release thread she isn't in. SSO slipped
> to 2.5. Each card shows where she picked up the old value, the message that changed it, and why
> she missed it. And how sure Unstale is: the ship date is 100%, she wrote it herself. The price is
> 80%: Unstale is assuming she read #sales, and it says so.
> That list cost zero LLM tokens. It's a graph traversal on HydraDB.

## 3. Catch it before it goes out (0:50 to 1:15)

Click "Try: Maya's slack". Click "Check before sending".

> At 9:00 Maya told #sales that 2.4 goes live today with SSO. Here it is one minute earlier.
> Unstale flags both facts, says who changed them and when, and warns that Tom and Lena read #sales
> and still believe the old date too.

## 4. It learns who reads what (1:15 to 1:35)

Back on Maya's brief, click "Never heard of it" on the Team plan card. Then open the Team tab and
scroll to "What the graph has learned about reading".

> Slack doesn't tell you who read a message, so "Maya's in #sales" is a guess. Every answer to a
> correction is evidence. "Never heard of it" goes into the graph as a read signal, her read rate for
> #sales drops, and the brief recomputes. Echoes and restatements count as evidence too, but people's
> answers are what teach it most. The graph gets sharper every run.

## 5. Agents go stale too (1:35 to 2:00)

Click "Support agent", then "End" on the timeline.

> Our support agent answers customers from its knowledge base channel. Three things in its context
> changed in channels it never reads: the price, the refund window, and the payments API. This block
> is what it should be told before it answers. It's also an MCP tool, so any agent can ask Unstale
> for its own corrections.

> Does it matter? We asked a support agent 31 customer questions. From its own knowledge base it
> gets 29% right, and a third of its answers are old values said with confidence. With Unstale's
> block it gets 94%, and repeats no old value, for about a hundred extra tokens.

## 6. The proof (2:00 to 2:35)

Show `docs/bench-twin.svg`.

> Our hand-written team scores precision 1.0, recall 0.92. But it's small and we wrote the answer
> key, so we built a harder test: 20 generated companies, 5,200 messages, where everyone has a hidden
> read rate for every channel and nothing tells the engine who actually read what. Learned exposure
> cuts false alarms by two thirds against our first version, scores the same as a model given the
> secret read rates, and a daily changelog, the status quo, is wrong nine times out of ten.
> All of it runs on HydraDB, and a Python twin agrees with it brief for brief.

## 7. Who buys it (2:35 to 2:50)

> The first buyer is revenue operations: the team that gets the escalation when a rep or a bot quotes
> the old price. Import last quarter's Slack export and Unstale shows who was working from which old
> version, and when. Unstale: find who's working from an old version of the truth. Built on HydraDB
> and SelfGraph.

Optional end card: `unstale-film-endcard.mp4`.
