"""Precompute what the landing page's timeline shows, from the real engine, so the page never waits on the API.

    python scripts/landing_data.py        # writes unstale/web/landing-data.json

For each moment in the Northwind week it records who holds which version of one fact, read from /api/graph, plus the
team-wide count of out-of-date beliefs from /api/team. The narration is written here by hand; every number in it is
checked against the data before the file is written.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update(UNSTALE_STORE="kuzu", UNSTALE_HOSTED="1", UNSTALE_KUZU_PATH=str(Path(tempfile.mkdtemp()) / "g.kuzu"))

from fastapi.testclient import TestClient  # noqa: E402

from unstale import api  # noqa: E402

PRICE, SHIP, REFUND = "plan:team|PRICED_AT", "release:2.4|SHIPS_ON", "policy:monthly-refunds|WINDOW"
END = "2026-07-01T17:00:00Z"

# (timestamp, day label, headline, narration, focus fact, draft shown in the window)
STEPS = [
    ("2026-06-22T10:30:00Z", "Mon 22 Jun", "Lena posts the price",
     "Lena posts the Team plan price in #sales: $39 a seat. Everyone who reads #sales has it, so everyone who works with it is current.",
     PRICE, None),
    ("2026-06-25T09:30:00Z", "Thu 25 Jun", "The price changes somewhere else",
     "Leadership signs off on $49 for renewals and Lena posts it in #pricing. Tom, Maya and the support bot aren't in #pricing, so they never see it. Nothing looks wrong, but from this moment each of them is behind.",
     PRICE, None),
    ("2026-06-26T16:00:00Z", "Fri 26 Jun", "A date moves in a thread they aren't in",
     "Priya moves release 2.4 from Monday 29 June to Friday 3 July, in #release. Maya tells customers when releases ship, and she isn't in #release.",
     SHIP, None),
    ("2026-06-29T08:55:00Z", "Mon 29 Jun", "Five minutes before she posts",
     "Maya is about to tell a customer that 2.4 goes live today. Unstale checks the draft against the record, flags it, and names the message that changed the date.",
     SHIP, "Brightline is pumped. Told Jordan 2.4 goes live today and SSO is in it!"),
    ("2026-07-01T12:00:00Z", "Wed 1 Jul", "An agent is behind too",
     "The refund window drops from 30 days to 14, in #pricing. The support agent doesn't read #pricing, so it keeps telling customers 30.",
     REFUND, None),
]


def versions_of(v: dict, g: dict) -> dict:
    """One version of the fact, with the message that set it (who, where, when) for the note beside it."""
    m = next((x for x in g["messages"] if x["id"] == v["message"]), None)
    return {"value": v["shown"], "current": v["current"], "since": v["since"],
            "by": m["author"] if m else None, "where": m["where"] if m else None}


def main() -> None:
    api.STATE.clear()
    with TestClient(api.app) as c:
        meta = c.get("/api/meta").json()
        names = {p["id"]: p["name"] for p in meta["people"]}
        people = [{"id": p["id"], "name": p["name"], "first": "Support bot" if p["kind"] == "agent" else p["name"].split()[0],
                   "initials": "AI" if p["kind"] == "agent" else "".join(w[0] for w in p["name"].split())[:2].upper(),
                   "kind": p["kind"]} for p in meta["people"]]
        steps = []
        for ts, day, title, text, slot, draft in STEPS:
            g = c.get("/api/graph", params={"slot": slot, "as_of": ts}).json()
            team = c.get("/api/team", params={"as_of": ts}).json()
            states = {}
            for p in g["people"]:
                states[p["id"]] = {"state": "ok" if p["in_sync"] else "no" if p["stale"] else "na", "believes": p["believes"]}
            steps.append({
                "ts": ts, "day": day, "title": title, "text": text, "slot": slot, "fact": g["title"], "draft": draft,
                "versions": [versions_of(v, g) for v in g["versions"]],
                "states": states, "behind_total": sum(len(r["stale"]) for r in team["people"])})
        end = c.get("/api/team", params={"as_of": END}).json()
        counts = {r["person"]: len(r["stale"]) for r in end["people"] if r["stale"]}
        proof = c.get("/api/proof").json()
    data = {"people": people, "steps": steps, "end": {"ts": END, "day": "Wed 1 Jul", "counts": counts,
                                                         "total": sum(counts.values())}, "proof": proof}
    # the narration makes claims; check them against what the engine returned
    assert steps[1]["states"]["person:tom"]["state"] == "no" and steps[1]["states"]["person:maya"]["state"] == "no"
    assert steps[1]["states"]["agent:support-bot"]["state"] == "no"
    assert steps[2]["states"]["person:maya"]["state"] == "no"
    assert steps[4]["states"]["agent:support-bot"]["state"] == "no"
    assert data["end"]["total"] == 13 and len(counts) == 5, counts
    out = ROOT / "unstale" / "web" / "landing-data.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"{len(steps)} steps, {data['end']['total']} stale beliefs at the end -> {out.relative_to(ROOT)}")
    for s in steps:
        print(s["day"], s["fact"], {names[k].split()[0]: v["state"] for k, v in s["states"].items()}, "behind", s["behind_total"])


if __name__ == "__main__":
    main()
