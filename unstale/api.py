"""HTTP API and demo UI.

    uvicorn unstale.api:app --port 8765
"""

from __future__ import annotations

import asyncio
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
from .config import ROOT as ROOT_DIR, Settings, dataset_path
from .engine import EXPOSURES_CYPHER, Engine, agent_context, check_draft
from .extract import extract_message
from .llm import USAGE, LLMError
from .timeline import checkpoints

WEB = Path(__file__).parent / "web"
STATE: dict[str, Any] = {}


_INIT = asyncio.Lock()


async def init_state() -> None:
    """Open the engine once per process. With the embedded store, or UNSTALE_BUILD_ON_START=1 (the single-container
    deployment), the graph does not outlive the process, so it is rebuilt here from the dataset and the committed
    extraction cache. Otherwise the API serves the namespace that scripts/ingest.py loaded."""
    async with _INIT:
        if "eng" in STATE:
            return
        cfg = Settings.load()
        ds = json.loads(dataset_path().read_text(encoding="utf-8"))
        build = cfg.store != "hydradb" or cfg.build_on_start
        eng = await Engine.open(ds, namespace=f"northwind-hosted-{int(time.time())}" if build else None)
        if build:
            await eng.load_directory()
            by_id = {m["id"]: m for m in ds["messages"]}
            for m in ds["messages"]:
                await eng.ingest(m, extract_message(m, ds, by_id.get(m["thread"]) if m.get("thread") else None))
        eng.remember_threads()
        STATE.update(ds=ds, eng=eng, claims=await eng.all_claims(), live=0, feedback=0)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_state()
    try:
        yield
    finally:
        await STATE["eng"].close()


app = FastAPI(title="Unstale", lifespan=lifespan)


@app.middleware("http")
async def ready(request, call_next):
    """Serverless hosts may skip lifespan events; make sure the engine exists before any route runs."""
    if "eng" not in STATE:
        await init_state()
    return await call_next(request)


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
    return {"name": d["name"], "start": d["start"], "end": d["end"], "namespace": eng().namespace, "store": eng().settings.store, "hosted": eng().settings.hosted,
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
    if Settings.load().hosted:
        raise HTTPException(403, "Sending is switched off on the public demo, so visitors don't change each other's graph. Run it locally to try it.")
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
    if Settings.load().hosted:
        STATE["feedback"] += 1
        if STATE["feedback"] > 80:
            raise HTTPException(429, "This demo instance has taken enough feedback for now; it resets when it restarts.")
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


@app.get("/api/graph")
async def fact_graph(slot: str, as_of: str) -> dict:
    """The part of the graph behind one fact: its versions, the messages that assert them, who saw which.

    The ``missing`` list is the point: people with no SAW edge to the message that changed the fact.
    """
    subject, attribute = slot.split("|", 1)
    t0, q0 = time.perf_counter(), eng().stats.queries
    t = rules.parse_ts(as_of)
    vers = [v for v in await eng().versions(subject, attribute) if rules.parse_ts(v.since) <= t]
    cur = Engine.pick(vers, as_of)
    model = await eng().read_model(as_of)
    claim_of: dict[str, dict] = {}
    for mid, cls in STATE["claims"].items():
        for cl in cls:
            if cl["slot"] == slot and rules.parse_ts(cl["ts"]) <= t:
                claim_of[mid] = cl
    version_nodes = [{"id": f"v{i}", "value": v.value, "shown": show(attribute, v.value), "since": v.since,
                      "until": v.until, "message": v.message, "current": cur is not None and v is cur}
                     for i, v in enumerate(vers)]
    by_value = {n["value"].lower(): n["id"] for n in version_nodes}
    msg_nodes, asserts = [], []
    for mid, cl in sorted(claim_of.items(), key=lambda kv: kv[1]["ts"]):
        m = eng()._messages.get(mid, {})
        msg_nodes.append({"id": mid, "author": name(m["author"]) if m else "", "where": where(m) if m else "",
                          "ts": cl["ts"], "text": (m.get("text") or "")[:160], "kind": cl["kind"],
                          "value": show(attribute, cl["value"])})
        target = next((n["id"] for n in version_nodes if n["message"] == mid), None) or by_value.get(cl["value"].lower())
        if target:
            asserts.append({"message": mid, "version": target, "kind": cl["kind"]})
    cur_msg = cur.message if cur else None
    people_out, saw, missing = [], [], []
    for p in ds()["people"]:
        pid = p["id"]
        exps = (await eng().exposures(pid, as_of, {slot})).get(slot, [])
        b = (await eng().beliefs(pid, as_of, slots={slot})).get(slot)
        relevant = subject in await eng().scope(pid)
        if not exps and not relevant:
            continue
        stale = bool(b and cur and not rules.same(b.value, cur.value))
        people_out.append({"id": pid, "name": p["name"], "kind": p["kind"], "role": p["role"], "relevant": relevant,
                           "believes": show(attribute, b.value) if b else None, "stale": stale,
                           "in_sync": bool(b and cur and not stale)})
        seen_msgs = set()
        for e in exps:
            seen_msgs.add(e.message)
            saw.append({"person": pid, "message": e.message, "strength": e.strength,
                        "rate": round(model.rate(pid, e.channel), 2) if e.strength == "weak" else 1.0,
                        "channel": e.channel})
        if cur_msg and cur_msg not in seen_msgs:
            missing.append({"person": pid, "message": cur_msg})
    return {"slot": slot, "subject": subject, "attribute": attribute, "as_of": as_of,
            "title": f"{next((x['name'] for x in ds()['subjects'] if x['id'] == subject), subject)}: {label(attribute)}",
            "versions": version_nodes, "messages": msg_nodes, "people": people_out, "asserts": asserts, "saw": saw,
            "missing": missing, "cypher": as_hydradb(EXPOSURES_CYPHER), "store": eng().settings.store,
            "graph_queries": eng().stats.queries - q0, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def as_hydradb(q: str) -> str:
    """The query as written for HydraDB (the engine rewrites it for the embedded store)."""
    return q.replace(" WHERE ", chr(10) + "WHERE ").replace(" RETURN ", chr(10) + "RETURN ")


EVAL = ROOT_DIR / "eval"


def _load(name: str) -> dict:
    p = EVAL / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@app.get("/api/proof")
async def proof() -> dict:
    """Every number the Proof panel shows, read from the committed result files (see scripts/ and eval/)."""
    res, base = _load("results.json"), _load("baselines.json")
    bench, curve, agent = _load("bench-twin.json"), _load("curve-twin.json"), _load("agent.json")
    summary = bench.get("summary", {})
    return {"northwind": {"unstale": res.get("engine", {}), "baselines": {
                k: {x: v[x] for x in ("precision", "recall", "f1", "tokens_per_brief", "told_what_they_knew")}
                for k, v in base.items()}},
            "bench": {k: summary.get(k) for k in ("orgs", "sprints_per_org", "messages", "people", "briefs_per_method",
                                                   "total", "same_sprint_after_n_prior_sprints", "calibration")},
            "curve": curve, "agent": agent.get("summary", {})}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
