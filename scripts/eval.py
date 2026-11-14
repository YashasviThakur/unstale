"""Score Unstale's belief diff against the scenario's answer key.

Checkpoints: 08:00 UTC every morning of the scenario, plus its end. At each one,
for every person and the agent, compare the stale slots Unstale reports with
the stale slots the ground-truth simulator finds.

    python scripts/eval.py                  # engine on the namespace from the last ingest
    python scripts/eval.py --baselines      # also run the LLM baselines at the end checkpoint
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from unstale import truth
from unstale.config import DATA, ROOT
from unstale.engine import Engine, current_namespace
from unstale.timeline import checkpoints

OUT = ROOT / "eval"


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp, "fp": fp, "fn": fn}


async def score_engine(ds: dict, ns: str) -> dict:
    eng = await Engine.open(ds, namespace=ns)
    tp = fp = fn = 0
    rows = []
    misses = []
    t0 = time.perf_counter()
    briefs = 0
    try:
        for cp in checkpoints(ds):
            gt = truth.stale_report(ds, cp)
            for p in ds["people"]:
                pid = p["id"]
                want = {x["slot"] for x in gt[pid]}
                got = {x.slot for x in await eng.diff(pid, cp)}
                briefs += 1
                tp += len(want & got)
                fp += len(got - want)
                fn += len(want - got)
                for s in sorted(got - want):
                    misses.append({"at": cp, "person": pid, "slot": s, "type": "false alarm"})
                for s in sorted(want - got):
                    misses.append({"at": cp, "person": pid, "slot": s, "type": "missed"})
            rows.append({"at": cp, "stale_in_truth": sum(len(v) for v in gt.values())})
    finally:
        await eng.close()
    ms = (time.perf_counter() - t0) * 1000 / max(briefs, 1)
    return {"namespace": ns, "checkpoints": rows, "briefs": briefs, "ms_per_brief": round(ms, 1),
            "llm_tokens_per_brief": 0, **prf(tp, fp, fn), "errors": misses,
            "graph": {"queries": eng.stats.queries, "avg_query_ms": round(eng.stats.query_ms / max(eng.stats.queries, 1), 1)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace")
    ap.add_argument("--baselines", action="store_true")
    a = ap.parse_args()
    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    ns = a.namespace or current_namespace()
    res = {"engine": asyncio.run(score_engine(ds, ns))}
    if a.baselines:
        from baselines import run_baselines  # noqa: PLC0415

        res["baselines"] = run_baselines(ds)
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    e = res["engine"]
    print(f"engine [{ns}]: precision {e['precision']} recall {e['recall']} f1 {e['f1']} "
          f"(tp={e['tp']} fp={e['fp']} fn={e['fn']}) over {e['briefs']} briefs, {e['ms_per_brief']} ms/brief")
    for err in e["errors"]:
        print(f"   {err['type']:<11} {err['at'][:10]} {err['person']:<18} {err['slot']}")
    for name, b in res.get("baselines", {}).items():
        print(f"{name}: precision {b['precision']} recall {b['recall']} f1 {b['f1']} "
              f"tokens/brief {b['tokens_per_brief']}")


if __name__ == "__main__":
    main()
