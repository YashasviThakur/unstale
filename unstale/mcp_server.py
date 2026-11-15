"""MCP server: lets any agent ask Unstale what in its context is out of date.

Two ways to run it:

* stdio, against a running Unstale API (one process owns the graph connection):

      uvicorn unstale.api:app --port 8765        # in one terminal
      python -m unstale.mcp_server               # stdio MCP server, for Claude Code, Cursor, etc.

* remote, mounted in the API itself at /mcp (set UNSTALE_MCP=1; the public Render demo does). Add it to an agent with
  ``claude mcp add --transport http unstale https://unstale.onrender.com/mcp``.

Tools:
    corrections(person)                    what this person or agent believes that is no longer true
    who_to_notify(subject, attribute)      who is still on the old value of a changed fact, where to tell them, and the draft
    check_before_sending(author, text)     does a draft repeat an outdated fact, and who reading it is stale
    who_believes(subject, attribute)       every version of one fact and who holds which
    give_feedback(person, slot, verdict)   tell Unstale whether a correction was news, so it learns who reads what
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

import httpx
from mcp.server.mcpserver import MCPServer

API = os.environ.get("UNSTALE_API", "http://127.0.0.1:8765")
NOW = os.environ.get("UNSTALE_AS_OF", "2026-07-01T17:00:00Z")
INSTRUCTIONS = ("Unstale tracks which version of each team fact every person and agent last saw. Call "
                "corrections() for yourself before answering from your context, and check_before_sending() "
                "before you send anything that states a date, price, owner or status. The demo team is Northwind "
                "Labs; people are ids like person:maya and agent:support-bot, and times run 22 Jun to 1 Jul 2026.")

Call = Callable[..., Awaitable[dict]]     # call(method, path, params=None, json=None) -> dict


def register(server: MCPServer, call: Call) -> MCPServer:
    """Add the Unstale tools to ``server``; ``call`` talks to the Unstale API (over HTTP, or in-process)."""

    @server.tool()
    async def corrections(person: str, as_of: str = NOW) -> str:
        """List what `person` (e.g. 'agent:support-bot' or 'person:maya') believes that is no longer true."""
        b = await call("GET", f"/api/brief/{person}", params={"as_of": as_of})
        if not b["items"]:
            return f"{person} is up to date as of {as_of}."
        lines = [f"{len(b['items'])} outdated beliefs for {person} as of {as_of}:"]
        for it in b["items"]:
            lines.append(f"- {it['subject']} {it['label']}: believes {it['believed']}, now {it['current']} "
                         f"(changed {it['changed_at'][:10]} by {it['change']['author']} in {it['change']['where']}; "
                         f"{round(it['confidence'] * 100)}% sure; slot {it['slot']}). {it['why'] or ''}")
        return "\n".join(lines)

    @server.tool()
    async def who_to_notify(subject: str, attribute: str, as_of: str = NOW) -> str:
        """For a changed fact (e.g. subject='plan:team', attribute='PRICED_AT'): who is still on the old value,
        which channels or DMs reach them, and a draft message. Nothing is sent or written."""
        f = await call("GET", "/api/fix", params={"slot": f"{subject}|{attribute}", "as_of": as_of})
        if not f["stale"]:
            return f"Nobody who works on {f['title']} is out of date as of {as_of}."
        lines = [f"{f['title']} is now {f['current']}. Still on the old value: "
                 + ", ".join(f"{x['name']} ({round(x['confidence'] * 100)}%)" for x in f["stale"]) + ".", "Plan:"]
        for st in f["plan"]:
            if st["kind"] == "post":
                at = f" and @mention {', '.join(st['mention_names'])}" if st["mention_names"] else ""
                lines.append(f"- Post in #{st['channel']} (reaches {', '.join(st['reach_names'])}){at}.")
            elif st["kind"] == "agent":
                lines.append(f"- Put the correction in {st['name']}'s context (no channel reaches it).")
            else:
                lines.append(f"- DM {st['name']}.")
        lines.append(f"Expected still out of date after: {f['expected_remaining']} of {len(f['stale'])}.")
        lines.append(f"Draft: {f['draft']}")
        return "\n".join(lines)

    @server.tool()
    async def check_before_sending(author: str, text: str, channel: str | None = None, as_of: str = NOW) -> str:
        """Check a draft against the current record before it is sent. Returns outdated facts and stale readers."""
        body = {"author": author, "text": text, "as_of": as_of}
        if channel:
            body["channel"] = channel
        res = await call("POST", "/api/check", json=body)
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
    async def who_believes(subject: str, attribute: str, as_of: str = NOW) -> str:
        """Show every version of one fact (e.g. subject='release:2.4', attribute='SHIPS_ON') and who holds which."""
        v = await call("GET", "/api/slot", params={"subject": subject, "attribute": attribute, "as_of": as_of})
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
    async def stale_report() -> str:
        """How out of date is this team? Stale person-days, the costliest missed changes, the channels changes leak out of, who lags."""
        r = await call("GET", "/api/report")
        h = r["headline"]
        lines = [f"{r['name']}, {r['days']} days: {h['people_affected']} of {r['people']} people and agents worked from an outdated fact, "
                 f"{h['stale_person_days']} stale person-days. {h['changes_missed']} of {h['changes']} changes were missed by someone; "
                 f"{h['still_stale_at_end']} outdated beliefs were still held at the end.", "Costliest missed changes:"]
        for c in r["changes"][:4]:
            lines.append(f"- {c['subject']} {c['label']}: {c['old']} -> {c['new']} ({c['where']}), {c['stale_person_days']} person-days, "
                         f"behind: {', '.join(c['people'])}")
        leak = [c for c in r["channels"] if c["leak_rate"] >= 0.5][:3]
        if leak:
            lines.append("Leakiest channels: " + "; ".join(f"{c['where']} ({round(c['leak_rate'] * 100)}% of its changes missed)" for c in leak))
        lines.append("Most behind: " + ", ".join(f"{x['name']} ({x['stale_person_days']} person-days)" for x in r["people_rows"][:3] if x["beliefs"]))
        return "\n".join(lines)

    @server.tool()
    async def give_feedback(person: str, slot: str, verdict: str, as_of: str = NOW) -> str:
        """Answer a correction for `person`: verdict 'news' (didn't know), 'knew', or 'neither' (never heard either value).

        `slot` is the id shown in corrections(), e.g. 'release:2.4|SHIPS_ON'. Unstale writes what this reveals about
        which channels the person reads into the graph, and later briefs use it.
        """
        res = await call("POST", "/api/feedback", json={"person": person, "slot": slot, "verdict": verdict, "as_of": as_of})
        if not res["evidence"]:
            return "Recorded. Nothing new to learn: the change was in a channel this person isn't in."
        rates = ", ".join(f"#{x['channel']} {round(x['rate'] * 100)}%" for x in res["rates"])
        return f"Recorded {res['evidence']} read signal(s). Estimated read rate now: {rates}."

    return server


def http_call(base: str) -> Call:
    """Talk to a running API over HTTP (the stdio server)."""
    async def call(method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        async with httpx.AsyncClient(base_url=base, timeout=90) as c:
            r = await c.request(method, path, params=params, json=json)
            r.raise_for_status()
            return r.json()
    return call


def asgi_call(app) -> Call:
    """Talk to the API in this process, with no network hop (the remote server mounted in the API)."""
    async def call(method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://unstale", timeout=90) as c:
            r = await c.request(method, path, params=params, json=json)
            if r.status_code >= 400:
                try:
                    detail = r.json().get("detail", r.text)
                except ValueError:
                    detail = r.text
                raise RuntimeError(str(detail))
            return r.json()
    return call


server = register(MCPServer(name="unstale", instructions=INSTRUCTIONS), http_call(API))

if __name__ == "__main__":
    server.run("stdio")
