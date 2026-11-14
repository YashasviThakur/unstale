"""MCP server: lets any agent ask Unstale what in its context is out of date.

It talks to the running Unstale API (one process owns the graph connection):

    uvicorn unstale.api:app --port 8765        # in one terminal
    python -m unstale.mcp_server               # stdio MCP server, for Claude Code, Cursor, etc.

Tools:
    corrections(person)                 what this person or agent believes that is no longer true
    check_before_sending(author, text)  does a draft repeat an outdated fact, and who reading it is stale
    who_believes(subject, attribute)    every version of one fact and who holds which
    give_feedback(person, slot, verdict) tell Unstale whether a correction was news, so it learns who reads what
"""

from __future__ import annotations

import os

import httpx
from mcp.server.mcpserver import MCPServer

API = os.environ.get("UNSTALE_API", "http://127.0.0.1:8765")
NOW = os.environ.get("UNSTALE_AS_OF", "2026-07-01T17:00:00Z")

server = MCPServer(
    name="unstale",
    instructions=("Unstale tracks which version of each team fact every person and agent last saw. Call "
                  "corrections() for yourself before answering from your context, and check_before_sending() "
                  "before you send anything that states a date, price, owner or status."),
)


def _get(path: str, **params) -> dict:
    r = httpx.get(f"{API}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


@server.tool()
def corrections(person: str, as_of: str = NOW) -> str:
    """List what `person` (e.g. 'agent:support-bot' or 'person:maya') believes that is no longer true."""
    b = _get(f"/api/brief/{person}", as_of=as_of)
    if not b["items"]:
        return f"{person} is up to date as of {as_of}."
    lines = [f"{len(b['items'])} outdated beliefs for {person} as of {as_of}:"]
    for it in b["items"]:
        lines.append(f"- {it['subject']} {it['label']}: believes {it['believed']}, now {it['current']} "
                     f"(changed {it['changed_at'][:10]} by {it['change']['author']} in {it['change']['where']}; "
                     f"{round(it['confidence'] * 100)}% sure; slot {it['slot']}). {it['why'] or ''}")
    return "\n".join(lines)


@server.tool()
def check_before_sending(author: str, text: str, channel: str | None = None, as_of: str = NOW) -> str:
    """Check a draft against the current record before it is sent. Returns outdated facts and stale readers."""
    body = {"author": author, "text": text, "as_of": as_of}
    if channel:
        body["channel"] = channel
    r = httpx.post(f"{API}/api/check", json=body, timeout=90)
    r.raise_for_status()
    res = r.json()
    if not res["issues"] and not res["stale_readers"]:
        return f"OK: {len(res['claims'])} facts checked, none contradict the current record."
    lines = []
    for i in res["issues"]:
        lines.append(f"OUTDATED: {i['subject_name']} {i['label']} is {i['current_shown']}, not {i['wrote_shown']} "
                     f"(changed {i['changed_at'][:10]} in {i['change_where']}).")
    for s in res["stale_readers"]:
        lines.append(f"READER STALE: {s['name']} still thinks {s['subject_name']} {s['label']} is "
                     f"{s['believes_shown']} (now {s['current_shown']}).")
    return "\n".join(lines)


@server.tool()
def who_believes(subject: str, attribute: str, as_of: str = NOW) -> str:
    """Show every version of one fact (e.g. subject='release:2.4', attribute='SHIPS_ON') and who holds which."""
    v = _get("/api/slot", subject=subject, attribute=attribute, as_of=as_of)
    lines = [v["title"]]
    for x in v["versions"]:
        lines.append(f"- {x['shown']} from {x['since'][:16]} ({x['author']}, {x['where']})"
                     f"{'' if x['until'] else ' [current]'}")
    for pid, b in v["people"].items():
        if b["believes"] is not None:
            note = " (STALE)" if b["stale"] and b["relevant"] else (" (stale, not their area)" if b["stale"] else "")
            lines.append(f"  {b['name']}: {b['shown']}{note}")
    return "\n".join(lines)


@server.tool()
def give_feedback(person: str, slot: str, verdict: str, as_of: str = NOW) -> str:
    """Answer a correction for `person`: verdict 'news' (didn't know), 'knew', or 'neither' (never heard either value).

    `slot` is the id shown in corrections(), e.g. 'release:2.4|SHIPS_ON'. Unstale writes what this reveals about
    which channels the person reads into the graph, and later briefs use it.
    """
    r = httpx.post(f"{API}/api/feedback", json={"person": person, "slot": slot, "verdict": verdict, "as_of": as_of},
                   timeout=60)
    r.raise_for_status()
    res = r.json()
    if not res["evidence"]:
        return "Recorded. Nothing new to learn: the change was in a channel this person isn't in."
    rates = ", ".join(f"#{x['channel']} {round(x['rate'] * 100)}%" for x in res["rates"])
    return f"Recorded {res['evidence']} read signal(s). Estimated read rate now: {rates}."


if __name__ == "__main__":
    server.run("stdio")
