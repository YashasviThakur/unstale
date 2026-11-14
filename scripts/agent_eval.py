"""Agents go stale too: does a support agent answer customers correctly?

A support agent reads its own knowledge-base channel. Prices, refund windows
and API status change in channels it never reads. At fixed times a customer
asks it about each fact it is responsible for, and it answers under four
context conditions:

  own        the messages the agent has read (its knowledge base), the usual setup
  unstale    the same, plus Unstale's correction block for this agent (a few lines)
  everything every message in the org up to now (the brute-force fix)
  rag        the top 8 messages in the whole org by embedding similarity to the question

Each answer is scored against the true current value, and we count answers
that repeat an outdated value: the confident, wrong kind.

    python scripts/agent_eval.py            # Northwind + 4 generated orgs (Groq, cached)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from baselines import render  # noqa: E402

from unstale import orgsim, rules, truth  # noqa: E402
from unstale.config import DATA, ROOT  # noqa: E402
from unstale.exposure import ReadModel  # noqa: E402
from unstale.llm import USAGE, LLMError, chat_json  # noqa: E402
from unstale.reference import Reference  # noqa: E402

OUT = ROOT / "eval"
AGENT = "agent:support-bot"
CONDITIONS = ["own", "unstale", "everything", "rag"]
TOP_K = 8

QUESTION = {
    "PRICED_AT": "How much does the {name} cost per seat per month?",
    "WINDOW": "How many days do I have to get a refund on the {name_lower}?",
    "STATUS": "Can I still build a new integration on {name}? Is it supported, deprecated or retired?",
    "SHIPS_ON": "When does {name} go live?",
}

SYSTEM = """You are the customer support agent for {org}. Answer the customer's question using only the
context you are given. Prefer the most recent information. Return JSON:
{{"value": "<the answer in this format: {fmt}>", "answer": "<one short sentence to the customer>"}}
If the context does not say, use "unknown" as the value."""


def norm(attribute: str, v: str) -> str:
    v = str(v).lower().strip()
    if attribute in ("PRICED_AT", "WINDOW"):
        d = re.findall(r"\d+", v)
        return d[0] if d else v
    if attribute == "STATUS":
        for w in ("retired", "deprecated", "supported"):
            if w in v:
                return w
    if attribute in ("SHIPS_ON",):
        d = re.findall(r"\d{4}-\d{2}-\d{2}", v)
        return d[0] if d else v
    return v


def correction_block(ref: Reference, ds: dict, agent: str, as_of: str) -> str:
    """What Unstale gives the agent: corrections for outdated sources, plus facts it has no source for."""
    names = {s["id"]: s["name"] for s in ds["subjects"]}
    labels = {k: v.get("label", k.lower()) for k, v in ds["attributes"].items()}
    lines = []
    for it in ref.diff(agent, as_of, ReadModel([e for e in ref.evidence if e.ts <= as_of])):
        subject, attribute = it.slot.split("|", 1)
        lines.append(f"- {names[subject]} {labels[attribute]}: now {it.current} (changed {it.changed_at[:10]}); "
                     f"your sources still say {it.believed}. Use the new value.")
    exps = ref.exposures(agent, as_of)
    for subject, hops in sorted(ref._scope[agent].items()):
        if hops:
            continue
        for attribute in ds["attributes"]:
            slot = rules.slot_key(subject, attribute)
            cur = ref.current(slot, as_of)
            if cur and slot not in exps:
                lines.append(f"- {names[subject]} {labels[attribute]}: {cur[0]} (set {cur[1][:10]}). "
                             f"None of your sources mention it.")
    if not lines:
        return "Unstale: nothing you have read has changed since."
    return "Unstale corrections to your context (newer than what you have read):\n" + "\n".join(lines)


class Rag:
    def __init__(self) -> None:
        from fastembed import TextEmbedding  # noqa: PLC0415

        self.model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(DATA / "cache" / "fastembed"))
        self.cache: dict[str, list[float]] = {}

    def vec(self, texts: list[str]) -> list[list[float]]:
        todo = [t for t in texts if t not in self.cache]
        if todo:
            for t, v in zip(todo, self.model.embed(todo)):
                self.cache[t] = list(v)
        return [self.cache[t] for t in texts]

    def top(self, question: str, docs: list[str], k: int = TOP_K) -> list[str]:
        q = self.vec([question])[0]
        ds = self.vec(docs)
        score = [sum(a * b for a, b in zip(q, d)) for d in ds]
        idx = sorted(range(len(docs)), key=lambda i: -score[i])[:k]
        return [docs[i] for i in sorted(idx)]


def questions(ds: dict, as_of: str) -> list[dict]:
    world = truth.simulate(ds, as_of)
    names = {s["id"]: s["name"] for s in ds["subjects"]}
    out = []
    sc = rules.scope(AGENT, ds["responsibility"], ds["links"])
    for subject, hops in sorted(sc.items()):
        if hops:
            continue
        for attribute, tmpl in QUESTION.items():
            slot = rules.slot_key(subject, attribute)
            if slot not in world.current:
                continue
            outdated = [v for v, _, _ in world.history.get(slot, [])[:-1]]
            out.append({"slot": slot, "attribute": attribute, "as_of": as_of, "current": world.current[slot][0],
                        "outdated": outdated,
                        "question": tmpl.format(name=names[subject], name_lower=names[subject].lower())})
    return out


def ask(ds: dict, q: dict, context: str) -> tuple[dict, int]:
    fmt = ds["attributes"][q["attribute"]]["format"]
    user = (f"Today is {q['as_of'][:10]}.\n\nCONTEXT:\n{context}\n\nCUSTOMER: {q['question']}")
    before = USAGE.prompt_tokens
    reply = chat_json(SYSTEM.format(org=ds["name"], fmt=fmt), user, tag="agent", max_tokens=600)
    return reply, USAGE.prompt_tokens - before


def run(datasets: list[tuple[dict, list[str]]], rag: Rag) -> dict:
    rows = []
    for ds, times in datasets:
        ref = Reference(ds).ingest_all()
        for as_of in times:
            t = rules.parse_ts(as_of)
            upto = [m for m in ds["messages"] if rules.parse_ts(m["ts"]) <= t]
            mine = [m for m in upto if ref.saw.get(AGENT, {}).get(m["id"])]
            own = "\n".join(render(ds, m) for m in mine) or "(no messages)"
            block = correction_block(ref, ds, AGENT, as_of)
            everything = "\n".join(render(ds, m) for m in upto)
            for q in questions(ds, as_of):
                docs = [render(ds, m) for m in upto]
                ctx = {"own": own, "unstale": own + "\n\n" + block, "everything": everything,
                       "rag": "\n".join(rag.top(q["question"], docs))}
                for cond in CONDITIONS:
                    try:
                        reply, tokens = ask(ds, q, ctx[cond])
                    except LLMError as e:
                        print("LLM error:", e)
                        time.sleep(20)
                        reply, tokens = ask(ds, q, ctx[cond])
                    got = norm(q["attribute"], reply.get("value", ""))
                    correct = got == norm(q["attribute"], q["current"])
                    stale = any(got == norm(q["attribute"], v) for v in q["outdated"]) and not correct
                    rows.append({"org": ds["name"], "as_of": as_of, "slot": q["slot"], "condition": cond,
                                 "question": q["question"], "current": q["current"], "answer": reply.get("value"),
                                 "correct": correct, "outdated_answer": stale, "prompt_tokens": tokens})
                print(f"{ds['name'][:16]:16s} {as_of[:10]} {q['slot']:36s} " + " ".join(
                    f"{r['condition']}={'Y' if r['correct'] else ('OLD' if r['outdated_answer'] else 'n')}"
                    for r in rows[-len(CONDITIONS):]), flush=True)
    return {"rows": rows}


def summarise(rows: list[dict]) -> dict:
    out = {}
    for cond in CONDITIONS:
        rs = [r for r in rows if r["condition"] == cond]
        n = len(rs)
        out[cond] = {"questions": n, "accuracy": round(sum(r["correct"] for r in rs) / n, 3),
                     "outdated_answers": sum(r["outdated_answer"] for r in rs),
                     "prompt_tokens_per_answer": round(sum(r["prompt_tokens"] for r in rs) / n)}
    # Only the questions whose answer changed at least once: where stale context can hurt.
    changed = [r for r in rows if r["condition"] == "own" and not r["correct"]]
    out["questions_where_own_context_is_wrong"] = len(changed)
    return out


def report(s: dict) -> str:
    names = {"own": "Agent's own knowledge base", "unstale": "**Own knowledge base + Unstale corrections**",
             "everything": "Every message in the org", "rag": "Vector RAG over every message (top 8)"}
    lines = ["# Agent eval: a support agent answering customers", "",
             "| Context | Correct | Confidently outdated answers | Prompt tokens per answer |", "|---|---|---|---|"]
    for c in ["own", "unstale", "everything", "rag"]:
        t = s[c]
        lines.append(f"| {names[c]} | {t['accuracy']:.0%} ({round(t['accuracy'] * t['questions'])}/{t['questions']}) | "
                     f"{t['outdated_answers']} | {t['prompt_tokens_per_answer']:,} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orgs", type=int, default=4)
    a = ap.parse_args()
    nw = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    datasets = [(nw, ["2026-06-26T12:00:00Z", "2026-06-30T12:00:00Z", "2026-07-01T12:00:00Z"])]
    for seed in range(101, 101 + a.orgs):
        ds = orgsim.generate(seed, 1)
        datasets.append((ds, [ds["end"]]))
    res = run(datasets, Rag())
    s = summarise(res["rows"])
    OUT.mkdir(exist_ok=True)
    (OUT / "agent.json").write_text(json.dumps({"summary": s, **res}, indent=1), encoding="utf-8")
    (OUT / "AGENT.md").write_text(report(s), encoding="utf-8")
    print(report(s))
    print(f"llm calls {USAGE.calls} (cached {USAGE.cached})")


if __name__ == "__main__":
    main()
