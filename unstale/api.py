"""HTTP API and demo UI.

    uvicorn unstale.api:app --port 8765
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import rules
from .config import dataset_path
from .engine import Engine, agent_context, check_draft
from .llm import USAGE, LLMError
from .timeline import checkpoints

WEB = Path(__file__).parent / "web"
STATE: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    ds = json.loads(dataset_path().read_text(encoding="utf-8"))
    eng = await Engine.open(ds)
    eng.remember_threads()
    STATE.update(ds=ds, eng=eng, claims=await eng.all_claims(), live=0)
    try:
        yield
    finally:
        await eng.close()


app = FastAPI(title="Unstale", lifespan=lifespan)


def ds() -> dict:
    return STATE["ds"]


def eng() -> Engine:
    return STATE["eng"]


def people() -> dict[str, dict]:
    return {p["id"]: p for p in ds()["people"]}


def name(pid: str) -> str:
    p = people().get(pid)
    if p:
        return p["name"]
    return ds()["external"].get(pid, pid)


def show(attribute: str, value: str) -> str:
    if attribute == "OWNED_BY":
        return name(value)
    return value


def label(attribute: str) -> str:
    return ds()["attributes"].get(attribute, {}).get("label", attribute.lower())


def where(m: dict) -> str:
    if m.get("channel"):
        return f"#{m['channel']}"
    if m["kind"] == "email":
        return "email"
    return "direct message"


def visible(m: dict, viewer: str) -> bool:
    if m["author"] == viewer or viewer in m.get("to", []) or viewer in m.get("cc", []):
        return True
    return bool(m.get("channel")) and viewer in ds()["channels"].get(m["channel"], [])


def why_missed(viewer: str, m: dict) -> str:
    p = people().get(viewer, {})
    if m.get("channel"):
        members = ds()["channels"].get(m["channel"], [])
        if viewer not in members:
            if p.get("kind") == "agent":
                return f"This agent doesn't read #{m['channel']}, so its context never got the change."
            return f"You're not in #{m['channel']}."
        if rules.is_ooo(p, m["ts"]):
            return "You were out of office."
        return f"You're in #{m['channel']} but never opened or reacted to it."
    if m["kind"] == "email":
        return "You weren't on the email."
    return "It was a direct message between other people."


def message_out(m: dict, as_of: str) -> dict:
    claims = []
    for cl in STATE["claims"].get(m["id"], []):
        cur = None
        hist = eng()._versions_cache.get(cl["subject"], {}).get(cl["attribute"])
        if hist is not None:
            cur = Engine.pick(hist, as_of)
        claims.append({"slot": cl["slot"], "label": label(cl["attribute"]), "value": show(cl["attribute"], cl["value"]),
                       "kind": cl["kind"], "outdated": bool(cur and not rules.same(cur.value, cl["value"])),
                       "now": show(cl["attribute"], cur.value) if cur else None})
    return {"id": m["id"], "ts": m["ts"], "author": m["author"], "author_name": name(m["author"]),
            "where": where(m), "channel": m.get("channel"), "kind": m["kind"], "thread": m.get("thread"),
            "subject_line": m.get("subject_line"), "to": [name(x) for x in m.get("to", []) + m.get("cc", [])],
            "text": m["text"], "reactions": [name(x) for x in m.get("reactions", [])], "claims": claims}


async def warm(as_of: str) -> None:
    for s in ds()["subjects"]:
        await eng().subject_versions(s["id"])


@app.get("/api/meta")
async def meta() -> dict:
    d = ds()
    return {"name": d["name"], "start": d["start"], "end": d["end"], "namespace": eng().namespace,
            "people": d["people"], "channels": d["channels"], "subjects": d["subjects"],
            "attributes": {k: v.get("label", k) for k, v in d["attributes"].items()},
            "checkpoints": checkpoints(d), "drafts": d["drafts"],
            "last_ts": max(m["ts"] for m in d["messages"])}


@app.get("/api/feed")
async def feed(viewer: str, as_of: str, channel: str | None = None) -> dict:
    await warm(as_of)
    t = rules.parse_ts(as_of)
    out = []
    for m in ds()["messages"]:
        if rules.parse_ts(m["ts"]) > t or not visible(m, viewer):
            continue
        if channel == "inbox" and m.get("channel"):
            continue
        if channel and channel != "inbox" and m.get("channel") != channel:
            continue
        out.append(message_out(m, as_of))
    return {"messages": out}


@app.get("/api/brief/{pid}")
async def brief(pid: str, as_of: str) -> dict:
    if pid not in people():
        raise HTTPException(404, "unknown person")
    t0 = time.perf_counter()
    q0 = eng().stats.queries
    model = await eng().read_model(as_of)
    items = await eng().diff(pid, as_of, model=model)
    ms = (time.perf_counter() - t0) * 1000
    msgs = eng()._messages
    out = []
    for it in items:
        cm = msgs.get(it.current_from or "", {})
        bm = msgs.get(it.believed_from, {})
        out.append({
            "slot": it.slot, "subject": it.subject_name, "attribute": it.attribute, "label": label(it.attribute),
            "believed": show(it.attribute, it.believed), "current": show(it.attribute, it.current),
            "changed_at": it.changed_at, "hops": it.hops,
            "you_saw": {"id": bm.get("id"), "author": name(bm["author"]) if bm else None,
                        "where": where(bm) if bm else None, "ts": bm.get("ts"), "text": bm.get("text")},
            "change": {"id": cm.get("id"), "author": name(cm["author"]) if cm else None,
                       "where": where(cm) if cm else None, "ts": cm.get("ts"), "text": cm.get("text")},
            "why": why_missed(pid, cm) if cm else None,
            "echo": it.echo_note,
            "confidence": it.confidence,
            "believed_via": {"strength": it.believed_strength, "channel": it.believed_channel,
                             "read_rate": round(model.rate(pid, it.believed_channel), 2)
                             if it.believed_strength == "weak" else 1.0},
        })
    return {"person": pid, "as_of": as_of, "items": out, "ms": round(ms, 1),
            "graph_queries": eng().stats.queries - q0, "llm_tokens": 0}


@app.get("/api/team")
async def team(as_of: str) -> dict:
    rows = []
    for p in ds()["people"]:
        items = await eng().diff(p["id"], as_of)
        rows.append({"person": p["id"], "name": p["name"], "role": p["role"], "kind": p["kind"],
                     "stale": [{"slot": it.slot, "subject": it.subject_name, "label": label(it.attribute),
                                "believed": show(it.attribute, it.believed), "current": show(it.attribute, it.current),
                                "confidence": it.confidence}
                               for it in items]})
    return {"as_of": as_of, "people": rows}


@app.get("/api/slot")
async def slot(subject: str, attribute: str, as_of: str) -> dict:
    view = await eng().slot_view(subject, attribute, as_of)
    for v in view["versions"]:
        v["shown"] = show(attribute, v["value"])
        m = eng()._messages.get(v["message"] or "", {})
        v["where"] = where(m) if m else None
        v["author"] = name(m["author"]) if m else None
    for pid, b in view["people"].items():
        b["name"] = name(pid)
        b["shown"] = show(attribute, b["believes"]) if b["believes"] else None
    names = {s["id"]: s["name"] for s in ds()["subjects"]}
    view["title"] = f"{names.get(subject, subject)}: {label(attribute)}"
    return view


class Draft(BaseModel):
    author: str
    text: str
    as_of: str
    channel: str | None = None
    to: list[str] = []


def audience_of(d: Draft) -> list[str]:
    if d.channel:
        return list(ds()["channels"].get(d.channel, []))
    return [x for x in d.to if x in people()]


@app.post("/api/check")
async def check(d: Draft) -> dict:
    before = USAGE.prompt_tokens + USAGE.completion_tokens
    try:
        res = await check_draft(eng(), d.author, d.text, d.as_of, audience_of(d))
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    names = {s["id"]: s["name"] for s in ds()["subjects"]}
    for i in res["issues"]:
        m = eng()._messages.get(i["changed_in"] or "", {})
        i.update(label=label(i["attribute"]), subject_name=names.get(i["subject"], i["subject"]),
                 wrote_shown=show(i["attribute"], i["wrote"]),
                 current_shown=show(i["attribute"], i["current"]),
                 change_where=where(m) if m else None, change_author=name(m["author"]) if m else None)
    for r in res["stale_readers"]:
        subject, attribute = r["slot"].split("|", 1)
        r.update(name=name(r["person"]), label=label(attribute), subject_name=names.get(subject, subject),
                 believes_shown=show(attribute, r["believes"]), current_shown=show(attribute, r["current"]))
    res["llm_tokens"] = USAGE.prompt_tokens + USAGE.completion_tokens - before
    return res


@app.post("/api/send")
async def send(d: Draft) -> dict:
    """Post a new message into the graph (demo: someone finally shares the change)."""
    from .extract import extract_message  # noqa: PLC0415

    last = max(m["ts"] for m in ds()["messages"])
    if rules.parse_ts(d.as_of) < rules.parse_ts(last):
        raise HTTPException(400, f"new messages must be at or after {last}")
    STATE["live"] += 1
    m = {"id": f"live{STATE['live']:03d}-{int(time.time())}", "ts": d.as_of, "kind": "slack" if d.channel else "email",
         "channel": d.channel, "thread": None, "author": d.author, "to": d.to, "cc": [], "subject_line": None,
         "text": d.text, "reactions": [], "mentions": [], "_truth": {"claims": [], "unread_by": []}}
    try:
        claims = extract_message(m, ds())
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    done = await eng().ingest(m, claims)
    ds()["messages"].append(m)
    STATE["claims"] = await eng().all_claims()
    return {"message": message_out(m, d.as_of), "claims": done}


class Feedback(BaseModel):
    person: str
    slot: str
    verdict: str          # news | knew | neither
    as_of: str


@app.post("/api/feedback")
async def feedback(f: Feedback) -> dict:
    """Someone answers a correction. The graph records what it reveals about who reads which channel."""
    if f.person not in people():
        raise HTTPException(404, "unknown person")
    try:
        res = await eng().record_feedback(f.person, f.slot, f.verdict, f.as_of)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    model = await eng().read_model(f.as_of)
    res["rates"] = [{"channel": c, "rate": round(model.rate(f.person, c), 2)} for c in res["channels"]]
    return res


@app.get("/api/learned")
async def learned(as_of: str) -> dict:
    """What the graph has learned about reading, as of a time."""
    model = await eng().read_model(as_of)
    ev = [e for e in await eng().load_evidence() if rules.parse_ts(e.ts) <= rules.parse_ts(as_of)]
    by_source: dict[str, int] = {}
    for e in ev:
        by_source[e.source] = by_source.get(e.source, 0) + 1
    rows = [{**r, "name": name(r["person"])} for r in model.table()]
    return {"as_of": as_of, "org_rate": round(model.org_rate(), 3), "evidence": len(ev), "by_source": by_source,
            "pairs": rows, "mode": eng().mode}


@app.get("/api/agent/{pid}/context")
async def agent_ctx(pid: str, as_of: str) -> dict:
    return {"agent": pid, "as_of": as_of, "context": await agent_context(eng(), pid, as_of)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
