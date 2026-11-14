"""Precompute what a plain vector store returns for each fact in the Northwind demo.

The Graph view shows this next to the graph: the store retrieves the right messages, and still can't say who read which.
Same embedding model as the measured baseline (scripts/baselines.py): BAAI/bge-small-en-v1.5 through fastembed.

    python scripts/vector_demo.py        # writes eval/vector-demo.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unstale.config import ROOT, dataset_path  # noqa: E402

TOP = 8


def main() -> None:
    from fastembed import TextEmbedding  # noqa: PLC0415

    ds = json.loads(dataset_path().read_text(encoding="utf-8"))
    names = {s["id"]: s["name"] for s in ds["subjects"]}
    labels = {k: v.get("label", k.lower()) for k, v in ds["attributes"].items()}
    msgs = ds["messages"]
    texts = [m["text"] for m in msgs]
    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    vecs = np.array(list(model.embed(texts)))
    slots = sorted({f"{c['subject']}|{c['attribute']}" for m in msgs for c in m["_truth"]["claims"]})
    out = {}
    for slot in slots:
        subject, attribute = slot.split("|", 1)
        q = f"What is the {names.get(subject, subject)} {labels.get(attribute, attribute)}?"
        qv = np.array(list(model.query_embed([q]))[0])
        scores = vecs @ qv / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(qv) + 1e-9)
        ranked = [{"message": msgs[i]["id"], "score": round(float(scores[i]), 3)} for i in np.argsort(-scores)[:TOP]]
        out[slot] = {"query": q, "model": "BAAI/bge-small-en-v1.5", "ranking": ranked}
    (ROOT / "eval" / "vector-demo.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out)} facts, top {TOP} messages each -> eval/vector-demo.json")


if __name__ == "__main__":
    main()
