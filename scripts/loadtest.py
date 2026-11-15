"""Load test: concurrent users on the real product endpoints, optionally with feedback writes while it serves.

    python scripts/loadtest.py --url https://unstale.onrender.com --users 10 --seconds 60 --label hosted
    python scripts/loadtest.py --url http://127.0.0.1:8765 --users 20 --seconds 60 --writes --label local

Every user loops over the same mix a visitor or an agent produces: morning briefs, the team table, a fact's
history, its graph, a Fix it plan and a pre-send check (the preset drafts, answered from the committed cache).
With --writes, 1 request in 10 is a "news to me / I knew this" answer, which writes ReadEvidence to HydraDB and
invalidates the per-person caches, so the reads after it go back to the graph. Results are appended to
eval/load.json, one entry per run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "eval" / "load.json"


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--writes", action="store_true", help="1 in 10 requests records feedback (never on a public demo)")
    ap.add_argument("--label", default="")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    base = a.url.rstrip("/")

    async with httpx.AsyncClient(base_url=base, timeout=60) as c:
        meta = (await c.get("/api/meta")).json()
        if a.writes and meta.get("hosted"):
            raise SystemExit("refusing --writes against a hosted demo: it caps feedback for visitors")
        people = [p["id"] for p in meta["people"]]
        checkpoints = meta["checkpoints"]
        late = checkpoints[len(checkpoints) // 2:]
        # facts that are stale for someone, from one brief per person at the last checkpoint
        slots: set[str] = set()
        for p in people:
            b = (await c.get(f"/api/brief/{p}", params={"as_of": checkpoints[-1]})).json()
            slots.update(i["slot"] for i in b["items"])
        slots_l = sorted(slots)
        drafts = meta["drafts"]

    def pick() -> tuple[str, str, dict]:
        r = rnd.random()
        t = rnd.choice(late)
        if a.writes and r < 0.10:
            return "feedback", "POST", {"url": "/api/feedback", "json": {
                "person": rnd.choice(people), "slot": rnd.choice(slots_l),
                "verdict": rnd.choice(["news", "knew"]), "as_of": t}}
        if r < 0.45:
            return "brief", "GET", {"url": f"/api/brief/{rnd.choice(people)}", "params": {"as_of": t}}
        if r < 0.58:
            return "team", "GET", {"url": "/api/team", "params": {"as_of": t}}
        s = rnd.choice(slots_l)
        subject, attribute = s.split("|", 1)
        if r < 0.70:
            return "slot", "GET", {"url": "/api/slot", "params": {"subject": subject, "attribute": attribute, "as_of": t}}
        if r < 0.82:
            return "graph", "GET", {"url": "/api/graph", "params": {"slot": s, "as_of": t}}
        if r < 0.92:
            return "fix", "GET", {"url": "/api/fix", "params": {"slot": s, "as_of": t}}
        d = rnd.choice(drafts)
        return "check", "POST", {"url": "/api/check", "json": {k: d[k] for k in ("author", "text", "as_of", "channel", "to") if k in d}}

    lat: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    stop = time.perf_counter() + a.seconds

    async def user(c: httpx.AsyncClient) -> None:
        while time.perf_counter() < stop:
            kind, method, kw = pick()
            t0 = time.perf_counter()
            try:
                r = await c.request(method, **kw)
                ok = r.status_code < 400 or (kind == "feedback" and r.status_code == 429)
            except httpx.HTTPError:
                ok = False
            ms = (time.perf_counter() - t0) * 1000
            if ok:
                lat.setdefault(kind, []).append(ms)
            else:
                errors[kind] = errors.get(kind, 0) + 1

    t_start = time.perf_counter()
    async with httpx.AsyncClient(base_url=base, timeout=60,
                                 limits=httpx.Limits(max_connections=a.users)) as c:
        await asyncio.gather(*(user(c) for _ in range(a.users)))
    wall = time.perf_counter() - t_start

    every = [x for xs in lat.values() for x in xs]
    total = len(every) + sum(errors.values())
    row = {
        "label": a.label, "url": base, "store": meta.get("store"), "users": a.users, "seconds": round(wall, 1),
        "writes": a.writes, "requests": total, "rps": round(total / wall, 1),
        "errors": sum(errors.values()), "error_rate": round(sum(errors.values()) / max(total, 1), 4),
        "p50_ms": round(pct(every, 50)), "p95_ms": round(pct(every, 95)), "p99_ms": round(pct(every, 99)),
        "by_endpoint": {k: {"n": len(v), "p50_ms": round(pct(v, 50)), "p95_ms": round(pct(v, 95)),
                            "mean_ms": round(statistics.fmean(v))} for k, v in sorted(lat.items())},
        "errors_by_endpoint": errors,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    runs = json.loads(OUT.read_text()) if OUT.exists() else []
    runs.append(row)
    OUT.write_text(json.dumps(runs, indent=1))
    print(json.dumps(row, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
