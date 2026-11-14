"""Load a dataset into HydraDB, message by message (Northwind unless --dataset says otherwise).

    python scripts/ingest.py                         # LLM extraction (Groq), fresh namespace
    python scripts/ingest.py --oracle-claims         # use the annotated claims instead (ablation)
    python scripts/ingest.py --dataset data/myteam.json   # e.g. from unstale.slack_import
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from unstale import rules
from pathlib import Path

from unstale.config import dataset_path
from unstale.engine import Engine, set_namespace
from unstale.extract import extract_message
from unstale.llm import USAGE


async def run(oracle: bool, namespace: str | None, activate: bool = True, dataset: str | None = None) -> None:
    path = Path(dataset) if dataset else dataset_path()
    ds = json.loads(path.read_text(encoding="utf-8"))
    stem = "northwind" if path.stem == "northwind" else path.stem.lower().replace("_", "-")
    ns = namespace or f"{stem}-{'oracle' if oracle else 'llm'}-{int(time.time())}"
    eng = await Engine.open(ds, namespace=ns)
    t0 = time.perf_counter()
    try:
        await eng.load_directory()
        by_id = {m["id"]: m for m in ds["messages"]}
        counts = {"update": 0, "restate": 0, "echo": 0}
        for m in ds["messages"]:
            if oracle:
                claims = m["_truth"]["claims"]
            else:
                claims = extract_message(m, ds, by_id.get(m["thread"]) if m.get("thread") else None)
            done = await eng.ingest(m, claims)
            for cl in done:
                counts[cl["kind"]] += 1
                if cl["kind"] == "echo":
                    print(f"  echo in {m['id']}: {cl['slot']} = {cl['value']} (repeats {cl['echoes']})")
        if activate:
            set_namespace(ns)
    finally:
        await eng.close()
    secs = time.perf_counter() - t0
    st = eng.stats
    print(f"namespace {ns}: {len(ds['messages'])} messages in {secs:.1f}s; claims {counts}")
    print(f"graph writes {st.writes} ({st.write_ms / max(st.writes, 1):.1f} ms avg), "
          f"reads {st.queries} ({st.query_ms / max(st.queries, 1):.1f} ms avg)")
    print(f"llm calls {USAGE.calls} (cached {USAGE.cached}), tokens in {USAGE.prompt_tokens}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-claims", action="store_true")
    ap.add_argument("--namespace")
    ap.add_argument("--no-activate", action="store_true", help="don't make this the namespace the API serves")
    ap.add_argument("--dataset", help="dataset JSON (default: UNSTALE_DATASET or data/northwind.json)")
    a = ap.parse_args()
    asyncio.run(run(a.oracle_claims, a.namespace, activate=not a.no_activate, dataset=a.dataset))


if __name__ == "__main__":
    main()
