"""How well does claim extraction hold up when people don't write like the scenario's author?

Every Northwind message is rewritten by an LLM in three messier styles (casual, terse, rambling), told to keep every
fact, name and number. The unchanged extractor then reads the rewrite and is scored against the same answer key as the
original (scripts/check_extraction.py). Messages with no claim (chit-chat, questions, proposals) are in the set, so a
rewrite that makes the extractor invent a claim shows up as a false positive.

    python scripts/robustness.py          # reads and writes the LLM cache, so it can be stopped and resumed

The rewrites are made by a model, so some drift from the original facts is possible. That counts against the extractor
here, which makes the numbers a lower bound.
"""

from __future__ import annotations

import json
import sys
import time

from unstale import rules
from unstale.config import DATA, ROOT
from unstale.extract import extract_message
from unstale.llm import USAGE, chat_json

STYLES = {
    "casual": "Rewrite it the way a busy person types in Slack: lowercase, slang, abbreviations, maybe an emoji, loose punctuation.",
    "terse": "Rewrite it as the shortest possible fragment someone would fire off from their phone: drop pronouns and filler, keep only what a teammate needs.",
    "rambling": "Rewrite it as a chatty message that wanders: add a short unrelated aside or a joke before or after, and put the fact in the middle.",
}
SYSTEM = """You rewrite short workplace messages in a different style for a test. Rules:
- Keep every fact exactly: every date, day, time, price, number, name, version and status must mean the same thing.
- Do not add any new fact, decision or number. Do not remove any fact. Questions stay questions, proposals stay proposals.
- Keep the speaker's role and the channel context. Return JSON: {"text": "<the rewritten message>"}"""


def key(c: dict) -> tuple[str, str, str]:
    return (c["subject"], c["attribute"], rules.norm_value(c["value"]))


def main() -> int:
    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in ds["messages"]}
    rows, per = [], {s: {"tp": 0, "fp": 0, "fn": 0, "msgs": 0, "exact": 0, "empty_fp": 0, "empty": 0} for s in ["original", *STYLES]}
    t0 = time.perf_counter()
    for i, m in enumerate(ds["messages"]):
        parent = by_id.get(m["thread"]) if m.get("thread") else None
        want = {key(c) for c in m["_truth"]["claims"]}
        variants = {"original": m["text"]}
        for style, how in STYLES.items():
            user = f"Message from {m['author']}:\n\"{m['text']}\"\n\nStyle: {how}"
            variants[style] = str(chat_json(SYSTEM, user, tag="rewrite", max_tokens=600).get("text", "")).strip() or m["text"]
        for style, text in variants.items():
            got = {key(c) for c in extract_message({**m, "text": text}, ds, parent)}
            p = per[style]
            p["tp"] += len(got & want)
            p["fp"] += len(got - want)
            p["fn"] += len(want - got)
            p["msgs"] += 1
            p["exact"] += got == want
            if not want:
                p["empty"] += 1
                p["empty_fp"] += bool(got)
            rows.append({"id": m["id"], "style": style, "text": text, "want": sorted(want), "got": sorted(got),
                         "ok": got == want})
        print(f"{i + 1}/{len(ds['messages'])} {m['id']}  {time.perf_counter() - t0:.0f}s  llm calls {USAGE.calls} (cached {USAGE.cached})", flush=True)

    out = {"messages": len(ds["messages"]), "claims_in_key": sum(len(m["_truth"]["claims"]) for m in ds["messages"]),
           "model": "openai/gpt-oss-120b", "styles": {}}
    for s, p in per.items():
        prec = p["tp"] / (p["tp"] + p["fp"]) if p["tp"] + p["fp"] else 1.0
        rec = p["tp"] / (p["tp"] + p["fn"]) if p["tp"] + p["fn"] else 1.0
        out["styles"][s] = {"precision": round(prec, 3), "recall": round(rec, 3),
                            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
                            "messages_exactly_right": p["exact"], "messages": p["msgs"],
                            "chit_chat_messages": p["empty"], "chit_chat_with_invented_claim": p["empty_fp"],
                            "tp": p["tp"], "fp": p["fp"], "fn": p["fn"]}
    out["rows"] = rows
    out["command"] = "python scripts/robustness.py"
    (ROOT / "eval" / "robustness.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for s, v in out["styles"].items():
        print(f"{s:9s} P {v['precision']:.2f}  R {v['recall']:.2f}  F1 {v['f1']:.2f}  exact {v['messages_exactly_right']}/{v['messages']}  "
              f"invented on chit-chat {v['chit_chat_with_invented_claim']}/{v['chit_chat_messages']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
