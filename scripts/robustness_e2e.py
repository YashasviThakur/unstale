"""End to end: do the corrections survive messy wording?

scripts/robustness.py rewrote every Northwind message in three styles and saved what the extractor read from each
(eval/robustness.json). Here every variant is ingested as its own graph (embedded store) and the morning briefs for all
8 people and agents at all 10 checkpoints are scored against the same hidden answer key as scripts/eval.py.

    python scripts/robustness_e2e.py     # no LLM calls: it reads the saved extractions
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from unstale import truth
from unstale.config import DATA, ROOT
from unstale.timeline import checkpoints


async def score(ds: dict, claims: dict[str, list[dict]], label: str, tmp: str) -> dict:
    os.environ.update(UNSTALE_STORE="kuzu", UNSTALE_KUZU_PATH=str(Path(tmp) / f"{label}.kuzu"))
    from unstale.engine import Engine  # noqa: PLC0415  (after the environment is set)

    eng = await Engine.open(ds, namespace=f"rob-{label}")
    tp = fp = fn = briefs = 0
    try:
        await eng.load_directory()
        for m in ds["messages"]:
            await eng.ingest(m, claims[m["id"]])
        eng.remember_threads()
        for cp in checkpoints(ds):
            gt = truth.stale_report(ds, cp)
            for p in ds["people"]:
                want = {x["slot"] for x in gt[p["id"]]}
                got = {x.slot for x in await eng.diff(p["id"], cp)}
                tp += len(want & got)
                fp += len(got - want)
                fn += len(want - got)
                briefs += 1
    finally:
        await eng.close()
    pr = tp / (tp + fp) if tp + fp else 1.0
    rc = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "briefs": briefs}


async def main() -> None:
    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    rob = json.loads((ROOT / "eval" / "robustness.json").read_text(encoding="utf-8"))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for style in rob["styles"]:
            claims = {m["id"]: [] for m in ds["messages"]}
            for r in rob["rows"]:
                if r["style"] == style:
                    claims[r["id"]] = [{"subject": s, "attribute": a, "value": v} for s, a, v in r["got"]]
            out[style] = await score(ds, claims, style, tmp)
            o = out[style]
            print(f"{style:9s} corrections: precision {o['precision']:.2f}  recall {o['recall']:.2f}  F1 {o['f1']:.2f}  "
                  f"(tp {o['tp']}, fp {o['fp']}, fn {o['fn']} over {o['briefs']} briefs)", flush=True)
    rob["end_to_end"] = out
    (ROOT / "eval" / "robustness.json").write_text(json.dumps(rob, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
