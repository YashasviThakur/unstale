"""Score LLM claim extraction against the scenario's annotated claims."""

from __future__ import annotations

import json
import sys

from unstale import rules
from unstale.config import DATA
from unstale.extract import extract_message
from unstale.llm import USAGE


def main() -> int:
    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in ds["messages"]}
    tp = fp = fn = 0
    for m in ds["messages"]:
        parent = by_id.get(m["thread"]) if m.get("thread") else None
        got = {(c["subject"], c["attribute"], rules.norm_value(c["value"])) for c in extract_message(m, ds, parent)}
        want = {(c["subject"], c["attribute"], rules.norm_value(c["value"])) for c in m["_truth"]["claims"]}
        tp += len(got & want)
        fp += len(got - want)
        fn += len(want - got)
        if got != want:
            print(f"{m['id']}: extra={sorted(got - want)} missing={sorted(want - got)}")
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    print(f"claims: precision {p:.2f}, recall {r:.2f} (tp={tp} fp={fp} fn={fn})")
    print(f"llm calls {USAGE.calls} (cached {USAGE.cached}), prompt tokens {USAGE.prompt_tokens}, "
          f"completion tokens {USAGE.completion_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
