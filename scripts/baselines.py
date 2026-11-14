"""Baselines for the same question Unstale answers: "what is this person wrong about?"

* recap: an LLM reads everything the person had access to (their channels, email
  and DMs) and lists facts they may be working from an old version of. This is
  what an AI channel recap does.
* org_llm: an LLM reads every message in the org, plus channel membership and
  out-of-office dates, and is asked to work out the same thing. It has strictly
  more information than Unstale; it just has to reason over it in tokens.
* vector_rag: messages are embedded (BAAI/bge-small-en-v1.5 via fastembed);
  the top 8 for "what changed that affects <person>" go to the LLM.

All three answer in the same JSON shape and are scored on the same slots as
Unstale, at the same checkpoints.
"""

from __future__ import annotations

import json
from typing import Any

from unstale import rules, truth
from unstale.extract import catalog, clean
from unstale.llm import USAGE, chat_json

CHECKPOINTS = ["2026-06-29T08:00:00Z", "2026-07-01T17:00:00Z"]
TOP_K = 8

ANSWER = """Answer in JSON: {"items": [{"subject": "<subject id>", "attribute": "<ATTRIBUTE>",
"believed": "<the outdated value they likely hold>", "current": "<the current value>"}]}
Use only subject ids and attributes from the catalog. List only facts where you think this person
holds an outdated value. If there are none, return {"items": []}."""


def name(ds: dict, pid: str) -> str:
    for p in ds["people"]:
        if p["id"] == pid:
            return p["name"]
    return ds["external"].get(pid, pid)


def render(ds: dict, m: dict) -> str:
    when = m["ts"].replace("T", " ").replace(":00Z", " UTC")
    if m.get("channel"):
        where = f"#{m['channel']}"
    else:
        rec = ", ".join(name(ds, x) for x in m["to"])
        cc = ", ".join(name(ds, x) for x in m["cc"])
        where = f"{m['kind']} to {rec}" + (f" cc {cc}" if cc else "")
    thread = f" (reply in thread {m['thread']})" if m.get("thread") else ""
    react = f" [reacted: {', '.join(name(ds, x) for x in m['reactions'])}]" if m.get("reactions") else ""
    return f"[{m['id']}] {when} {where}{thread} {name(ds, m['author'])}: {m['text']}{react}"


def profile(ds: dict, pid: str) -> str:
    p = next(x for x in ds["people"] if x["id"] == pid)
    work = [f"{t.lower()} {s}" for a, t, s in ds["responsibility"] if a == pid]
    links = "; ".join(f"{a} {t} {b}" for a, t, b in ds["links"])
    ooo = f" Out of office: {p['ooo']}." if p.get("ooo") else ""
    return (f"{p['name']} ({pid}), {p['role']}. Responsible for: {', '.join(work)}. "
            f"How subjects relate: {links}.{ooo}")


def visible(ds: dict, m: dict, pid: str) -> bool:
    if m["author"] == pid or pid in m["to"] or pid in m["cc"]:
        return True
    return bool(m.get("channel")) and pid in ds["channels"].get(m["channel"], [])


def upto(ds: dict, as_of: str) -> list[dict]:
    t = rules.parse_ts(as_of)
    return [m for m in ds["messages"] if rules.parse_ts(m["ts"]) <= t]


def recap(ds: dict, pid: str, as_of: str) -> list[dict]:
    msgs = [render(ds, m) for m in upto(ds, as_of) if visible(ds, m, pid)]
    user = "\n".join([catalog(ds), "", f"PERSON: {profile(ds, pid)}", f"NOW: {as_of}", "",
                      "MESSAGES THIS PERSON HAD ACCESS TO:", *msgs, "",
                      "Which facts relevant to this person's work changed, such that they may be working from an "
                      "outdated value?", ANSWER])
    return clean_items(chat_json("You brief a teammate on what changed.", user, tag="recap", max_tokens=1500), ds)


def org_llm(ds: dict, pid: str, as_of: str) -> list[dict]:
    msgs = [render(ds, m) for m in upto(ds, as_of)]
    members = "; ".join(f"#{c}: {', '.join(name(ds, x) for x in v)}" for c, v in ds["channels"].items())
    user = "\n".join([catalog(ds), "", f"CHANNEL MEMBERS: {members}", f"PERSON: {profile(ds, pid)}", f"NOW: {as_of}",
                      "", "EVERY MESSAGE IN THE ORG SO FAR:", *msgs, "",
                      "A person sees messages in channels they belong to (unless out of office), emails and DMs "
                      "addressed to them, and anything they posted, reacted to or replied to. Work out which facts "
                      "relevant to this person's work they are holding an outdated value for.", ANSWER])
    return clean_items(chat_json("You track who knows what in a company.", user, tag="org_llm", max_tokens=2000), ds)


_EMB: dict[str, Any] = {}


def _embedder():
    if "model" not in _EMB:
        from fastembed import TextEmbedding  # noqa: PLC0415

        _EMB["model"] = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _EMB["model"]


def vector_rag(ds: dict, pid: str, as_of: str) -> list[dict]:
    import numpy as np  # noqa: PLC0415

    msgs = upto(ds, as_of)
    texts = [render(ds, m) for m in msgs]
    model = _embedder()
    key = tuple(m["id"] for m in msgs)
    if _EMB.get("key") != key:
        _EMB["key"], _EMB["vecs"] = key, np.array(list(model.embed(texts)))
    p = next(x for x in ds["people"] if x["id"] == pid)
    q = f"What changed recently that affects {p['name']}, {p['role']}? {profile(ds, pid)}"
    qv = np.array(list(model.query_embed([q]))[0])
    vecs = _EMB["vecs"]
    scores = vecs @ qv / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(qv) + 1e-9)
    top = [texts[i] for i in np.argsort(-scores)[:TOP_K]]
    user = "\n".join([catalog(ds), "", f"PERSON: {profile(ds, pid)}", f"NOW: {as_of}", "",
                      f"THE {TOP_K} MOST RELEVANT MESSAGES (vector search):", *top, "",
                      "Which facts relevant to this person's work changed, such that they may be working from an "
                      "outdated value?", ANSWER])
    return clean_items(chat_json("You brief a teammate on what changed.", user, tag="vector_rag", max_tokens=1500), ds)


def clean_items(reply: dict, ds: dict) -> list[dict]:
    raw = {"claims": [{"subject": i.get("subject"), "attribute": i.get("attribute"),
                       "value": i.get("current") or "?"} for i in (reply.get("items") or []) if isinstance(i, dict)]}
    return clean(raw, ds)


def run_baselines(ds: dict, which: tuple[str, ...] = ("recap", "org_llm", "vector_rag")) -> dict:
    fns = {"recap": recap, "org_llm": org_llm, "vector_rag": vector_rag}
    out = {}
    for b in which:
        tp = fp = fn = 0
        told_known = 0
        before = USAGE.by_tag.get(b, {}).get("prompt_tokens", 0) + USAGE.by_tag.get(b, {}).get("completion_tokens", 0)
        briefs = 0
        errors = []
        for cp in CHECKPOINTS:
            gt = truth.stale_report(ds, cp)
            world = truth.simulate(ds, cp)
            for p in ds["people"]:
                pid = p["id"]
                want = {x["slot"] for x in gt[pid]}
                got = {rules.slot_key(i["subject"], i["attribute"]) for i in fns[b](ds, pid, cp)}
                briefs += 1
                tp += len(want & got)
                fp += len(got - want)
                fn += len(want - got)
                for s in got - want:
                    cur = world.current.get(s)
                    mine = world.beliefs.get(pid, {}).get(s)
                    if cur and mine and rules.same(cur[0], mine.value):
                        told_known += 1
                    errors.append({"at": cp, "person": pid, "slot": s, "type": "false alarm"})
                for s in want - got:
                    errors.append({"at": cp, "person": pid, "slot": s, "type": "missed"})
        used = USAGE.by_tag.get(b, {})
        tokens = used.get("prompt_tokens", 0) + used.get("completion_tokens", 0) - before
        p_ = tp / (tp + fp) if tp + fp else 1.0
        r_ = tp / (tp + fn) if tp + fn else 1.0
        out[b] = {"precision": round(p_, 3), "recall": round(r_, 3),
                  "f1": round(2 * p_ * r_ / (p_ + r_), 3) if p_ + r_ else 0.0, "tp": tp, "fp": fp, "fn": fn,
                  "told_what_they_knew": told_known, "briefs": briefs,
                  "tokens_per_brief": round(tokens / max(briefs, 1)), "errors": errors}
        print(f"{b}: P {out[b]['precision']} R {out[b]['recall']} F1 {out[b]['f1']} "
              f"tokens/brief {out[b]['tokens_per_brief']} told-what-they-knew {told_known}", flush=True)
    return out


if __name__ == "__main__":
    import sys

    from unstale.config import DATA, ROOT

    dset = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    pick = tuple(sys.argv[1:]) or ("recap", "org_llm", "vector_rag")
    res = run_baselines(dset, pick)
    path = ROOT / "eval" / "baselines.json"
    path.parent.mkdir(exist_ok=True)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old.update(res)
    path.write_text(json.dumps(old, indent=2), encoding="utf-8")
