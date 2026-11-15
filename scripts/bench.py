"""Benchmark: many generated orgs, reading the engine can't see.

Each org (unstale/orgsim.py) runs for several two-week sprints. At 08:00 every
working day every person and the support agent gets a brief, and the brief is
scored against the hidden answer key. Methods:

  v1            every channel member read every message (the original Unstale)
  strong        only interactions count (posted, replied, reacted, mentioned, emailed)
  digest        a daily changelog: every change since the last brief to something in your scope
  learned       Unstale now: read rates learned from echoes, restatements and feedback
  learned-noFB  the same, from echoes and restatements only (nobody clicks anything)
  ceiling       the same model given the generator's true hidden read rates

People answer the corrections they get ("news to me", "I knew", "never heard
either") 70% of the time, truthfully. That feedback is written to the graph and
used from the next brief on.

    python scripts/bench.py                         # 20 orgs x 3 sprints on the Python twin
    python scripts/bench.py --hydradb --orgs 4      # the same loop on HydraDB (slower)
    python scripts/bench.py --hydradb --parity 2    # check HydraDB and the twin agree brief for brief
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unstale import orgsim, rules, truth  # noqa: E402
from unstale.config import ROOT  # noqa: E402
from unstale.exposure import THRESHOLD, Evidence, ReadModel, evidence_from_verdict, stale_probability  # noqa: E402
from unstale.reference import Reference  # noqa: E402

OUT = ROOT / "eval"
DOCS = ROOT / "docs"
METHODS = ["v1", "strong", "digest", "learned-noFB", "learned", "ceiling"]
RESPONSE_RATE = 0.7


class Hidden(ReadModel):
    """The generator's true read rates: what a perfect exposure model would know."""

    def __init__(self, rates: dict[str, float]) -> None:
        super().__init__([])
        self.rates = rates

    def rate(self, person: str, channel: str | None) -> float:
        return self.rates.get(f"{person}|{channel}", 0.5)


def mornings(start: str, end: str) -> list[str]:
    d = rules.parse_ts(start).replace(hour=8) + timedelta(days=1)
    e, out = rules.parse_ts(end), []
    while d < e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%dT%H:%M:%SZ"))
        d += timedelta(days=1)
    return out + [end]


# ------------------------------------------------------------------ backends
class TwinBackend:
    name = "python twin"

    def __init__(self, ds: dict) -> None:
        self.ds, self.ref = ds, Reference(ds)

    async def ingest(self) -> None:
        self.ref.ingest_all()

    async def exposures(self, pid: str, cp: str):
        return self.ref.exposures(pid, cp)

    async def scope(self, pid: str) -> dict[str, int]:
        return self.ref._scope[pid]

    async def current(self, slot: str, cp: str) -> tuple[str, str] | None:
        v = self.ref.current(slot, cp)
        return (v[0], v[1]) if v else None

    async def changes(self, t0: str, t1: str) -> set[str]:
        a, b = rules.parse_ts(t0), rules.parse_ts(t1)
        return {s for s, vs in self.ref.versions.items() for v in vs if a < rules.parse_ts(v[1]) <= b}

    async def implicit(self) -> list[Evidence]:
        return list(self.ref.evidence)

    async def store_feedback(self, items: list[Evidence], cp: str) -> None:
        pass

    async def close(self) -> None:
        pass


class GraphBackend:
    name = "HydraDB"

    def __init__(self, ds: dict, ns: str) -> None:
        self.ds, self.ns, self.eng = ds, ns, None

    async def ingest(self) -> None:
        from unstale.engine import Engine  # noqa: PLC0415

        self.eng = await Engine.open(self.ds, namespace=self.ns)
        await self.eng.load_directory()
        for m in self.ds["messages"]:
            await self.eng.ingest(m, m["_truth"]["claims"])

    async def exposures(self, pid: str, cp: str):
        return await self.eng.exposures(pid, cp)

    async def scope(self, pid: str) -> dict[str, int]:
        return await self.eng.scope(pid)

    async def current(self, slot: str, cp: str) -> tuple[str, str] | None:
        s, a = slot.split("|", 1)
        v = await self.eng.truth_at(s, a, cp)
        return (v.value, v.since) if v else None

    async def changes(self, t0: str, t1: str) -> set[str]:
        a, b = rules.parse_ts(t0), rules.parse_ts(t1)
        out = set()
        for subj in self.ds["subjects"]:
            for attr, vs in (await self.eng.subject_versions(subj["id"])).items():
                if any(a < rules.parse_ts(v.since) <= b for v in vs):
                    out.add(rules.slot_key(subj["id"], attr))
        return out

    async def implicit(self) -> list[Evidence]:
        return [e for e in await self.eng.load_evidence() if e.source != "feedback"]

    async def store_feedback(self, items: list[Evidence], cp: str) -> None:
        if items:
            await self.eng.write_evidence(items, origin=f"fb-{cp[:13]}")

    async def close(self) -> None:
        if self.eng:
            await self.eng.close()


# --------------------------------------------------------------------- core
async def brief(be, pid: str, cp: str, exps, model: ReadModel, threshold: float):
    """Same decision rule as Engine.diff, over exposures fetched once."""
    sc = await be.scope(pid)
    out = []
    for slot, es in exps.items():
        if slot.split("|", 1)[0] not in sc:
            continue
        cur = await be.current(slot, cp)
        if cur is None:
            continue
        p, b = stale_probability(es, cur[0], pid, model)
        if b is not None and p >= threshold:
            out.append((slot, b.value, cur[0], p))
    return out


def tally(t: dict, want: set, got: set) -> None:
    t["tp"] += len(want & got)
    t["fp"] += len(got - want)
    t["fn"] += len(want - got)
    t["briefs"] += 1


def prf(t: dict) -> dict:
    tp, fp, fn = t["tp"], t["fp"], t["fn"]
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp, "fp": fp, "fn": fn,
            "briefs": t["briefs"], "false_alarms_per_100_briefs": round(100 * fp / max(t["briefs"], 1), 1)}


async def run_org(seed: int, sprints: int, threshold: float, backend: str, ns_prefix: str) -> dict:
    ds = orgsim.generate(seed, sprints)
    be = GraphBackend(ds, f"{ns_prefix}-{seed:03d}-{int(time.time())}") if backend == "hydradb" else TwinBackend(ds)
    t0 = time.perf_counter()
    await be.ingest()
    ingest_s = time.perf_counter() - t0
    hidden = Hidden(ds["_hidden"]["read_rates"])
    implicit = await be.implicit()
    rng = random.Random(seed * 1009)
    feedback: list[Evidence] = []
    fb_by_sprint: dict[int, list[Evidence]] = defaultdict(list)
    # Control: the same people answer the same corrections, but each verdict is a coin flip.
    rng_ctl = random.Random(seed * 4241)
    fb_ctl_by_sprint: dict[int, list[Evidence]] = defaultdict(list)
    totals = {m: defaultdict(int) for m in METHODS}
    per_sprint = {m: [defaultdict(int) for _ in range(sprints)] for m in METHODS}
    calib = defaultdict(lambda: [0, 0])     # decile -> [stale, total], learned model
    test_cache: dict[tuple[str, str], dict] = {}
    briefs_out = []
    prev = ds["start"]
    for k, (a, b) in enumerate(ds["sprints"]):
        for cp in mornings(a, b):
            gt = truth.stale_report(ds, cp)
            world = truth.simulate(ds, cp)
            imp = [e for e in implicit if e.ts <= cp]
            models = {"v1": ReadModel(fixed=1.0), "strong": ReadModel(fixed=0.0), "learned-noFB": ReadModel(imp),
                      "learned": ReadModel(imp + feedback), "ceiling": hidden}
            changed = await be.changes(prev, cp)
            new_fb: list[Evidence] = []
            for p in ds["people"]:
                pid = p["id"]
                want = {x["slot"] for x in gt[pid]}
                exps = await be.exposures(pid, cp)
                if k == sprints - 1:
                    test_cache[(pid, cp)] = exps
                sc = await be.scope(pid)
                for name, model in models.items():
                    items = await brief(be, pid, cp, exps, model, threshold)
                    got = {s for s, *_ in items}
                    tally(totals[name], want, got)
                    tally(per_sprint[name][k], want, got)
                    if name == "learned":
                        briefs_out.append({"at": cp, "person": pid, "items": [[s, round(pr, 3)] for s, _, _, pr in items]})
                        # Calibration over every candidate the model scored, not only those shown.
                        for slot, es in exps.items():
                            if slot.split("|", 1)[0] not in sc:
                                continue
                            cur = await be.current(slot, cp)
                            if cur is None:
                                continue
                            pr, _ = stale_probability(es, cur[0], pid, model)
                            if pr > 0.02:
                                d = calib[min(int(pr * 10), 9)]
                                d[0] += slot in want
                                d[1] += 1
                        if p["kind"] == "person":
                            for slot, believed, current, _ in items:
                                if rng.random() > RESPONSE_RATE:
                                    continue
                                tb = world.beliefs.get(pid, {}).get(slot)
                                verdict = "neither" if tb is None else ("knew" if rules.same(tb.value, current) else "news")
                                new_fb += evidence_from_verdict(pid, verdict, current, believed,
                                                                exps.get(slot, []), cp)
                                fb_ctl_by_sprint[k] += evidence_from_verdict(
                                    pid, rng_ctl.choice(["news", "knew"]), current, believed, exps.get(slot, []), cp)
                digest = {s for s in changed if s.split("|", 1)[0] in sc}
                tally(totals["digest"], want, digest)
                tally(per_sprint["digest"][k], want, digest)
            feedback += new_fb
            fb_by_sprint[k] += new_fb
            await be.store_feedback(new_fb, cp)
            prev = cp

    # Sharper every run: score the last sprint again with evidence from only the first n sprints
    # (plus what it learns online inside the sprint), for n = 0 .. sprints-1.
    runs, runs_ctl = [], []
    a, b = ds["sprints"][-1]
    for n in range(sprints):
        cut = ds["sprints"][n - 1][1] if n else ds["start"]
        for arm, fb_src, out in (("real", fb_by_sprint, runs), ("control", fb_ctl_by_sprint, runs_ctl)):
            base_ev = [e for e in implicit if e.ts <= cut] + [e for j in range(n) for e in fb_src[j]]
            online: list[Evidence] = []
            rng2 = random.Random(seed * 7919 + n)
            rng3 = random.Random(seed * 6373 + n)
            t = defaultdict(int)
            for cp in mornings(a, b):
                gt = truth.stale_report(ds, cp)
                world = truth.simulate(ds, cp)
                model = ReadModel(base_ev + [e for e in implicit if a <= e.ts <= cp] + online)
                for p in ds["people"]:
                    pid = p["id"]
                    exps = test_cache[(pid, cp)]
                    items = await brief(be, pid, cp, exps, model, threshold)
                    tally(t, {x["slot"] for x in gt[pid]}, {s for s, *_ in items})
                    if p["kind"] == "person":
                        for slot, believed, current, _ in items:
                            if rng2.random() > RESPONSE_RATE:
                                continue
                            tb = world.beliefs.get(pid, {}).get(slot)
                            verdict = "neither" if tb is None else ("knew" if rules.same(tb.value, current) else "news")
                            if arm == "control":
                                verdict = rng3.choice(["news", "knew"])
                            online += evidence_from_verdict(pid, verdict, current, believed, exps.get(slot, []), cp)
            out.append(dict(t))
    await be.close()
    return {"seed": seed, "backend": be.name, "people": len(ds["people"]), "channels": len(ds["channels"]),
            "messages": len(ds["messages"]), "ingest_s": round(ingest_s, 1),
            "totals": {m: dict(v) for m, v in totals.items()},
            "per_sprint": {m: [dict(x) for x in v] for m, v in per_sprint.items()},
            "runs": runs, "runs_control": runs_ctl, "calibration": {str(k): v for k, v in calib.items()},
            "feedback_evidence": len(feedback), "implicit_evidence": len(implicit), "briefs": briefs_out}


def merge(rows: list[dict], key: str, sprints: int) -> dict:
    out = {m: defaultdict(int) for m in METHODS}
    for r in rows:
        for m in METHODS:
            for k, v in r[key][m].items():
                out[m][k] += v
    return {m: prf(v) for m, v in out.items()}


def summarise(rows: list[dict], sprints: int, threshold: float, backend: str) -> dict:
    total = merge(rows, "totals", sprints)
    curve = {m: [] for m in METHODS}
    for k in range(sprints):
        for m in METHODS:
            t = defaultdict(int)
            for r in rows:
                for a, v in r["per_sprint"][m][k].items():
                    t[a] += v
            curve[m].append(prf(t))
    runs = []
    for n in range(sprints):
        t = defaultdict(int)
        for r in rows:
            for a, v in r["runs"][n].items():
                t[a] += v
        runs.append(prf(t))
    cal = defaultdict(lambda: [0, 0])
    for r in rows:
        for k, (s, n) in r["calibration"].items():
            cal[int(k)][0] += s
            cal[int(k)][1] += n
    calibration = [{"bucket": f"{k / 10:.1f}-{(k + 1) / 10:.1f}", "stale": s, "n": n, "rate": round(s / n, 3)}
                   for k, (s, n) in sorted(cal.items())]
    return {"backend": backend, "orgs": len(rows), "sprints_per_org": sprints, "threshold": threshold,
            "response_rate": RESPONSE_RATE,
            "messages": sum(r["messages"] for r in rows), "people": sum(r["people"] for r in rows),
            "briefs_per_method": total["v1"]["briefs"], "total": total, "by_sprint": curve,
            "same_sprint_after_n_prior_sprints": runs, "calibration": calibration,
            "ingest_s_per_org": round(sum(r["ingest_s"] for r in rows) / len(rows), 1)}


def chart(summary: dict) -> str:
    """A small hand-written SVG: precision and recall by method."""
    labels = {"v1": "v1: everyone in the channel read it", "strong": "Interactions only", "digest": "Daily changelog",
              "learned-noFB": "Learned, no feedback", "learned": "Unstale (learned)", "ceiling": "True read rates (ceiling)"}
    rows = [m for m in ["digest", "strong", "v1", "learned-noFB", "learned", "ceiling"]]
    w, row_h, left, top = 760, 44, 260, 58
    h = top + row_h * len(rows) + 40
    x = lambda v: left + v * (w - left - 30)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="system-ui, sans-serif" font-size="13">',
           '<style>text{fill:#1d1a16}.mut{fill:#6f675c}.grid{stroke:#e3dccf}</style>',
           f'<rect width="{w}" height="{h}" fill="#faf7f0"/>',
           f'<text x="16" y="24" font-size="15" font-weight="600">Stale-belief detection on {summary["orgs"]} generated orgs '
           f'({summary["briefs_per_method"]:,} briefs per method)</text>']
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        out.append(f'<line class="grid" x1="{x(v):.0f}" y1="{top - 6}" x2="{x(v):.0f}" y2="{h - 34}"/>')
        out.append(f'<text class="mut" x="{x(v):.0f}" y="{h - 18}" text-anchor="middle">{v:.2f}</text>')
    for i, m in enumerate(rows):
        y = top + i * row_h
        s = summary["total"][m]
        bold = ' font-weight="600"' if m == "learned" else ""
        out.append(f'<text x="16" y="{y + 20}"{bold}>{labels[m]}</text>')
        out.append(f'<rect x="{left}" y="{y + 6}" width="{x(s["precision"]) - left:.0f}" height="12" fill="#17130f"/>')
        out.append(f'<rect x="{left}" y="{y + 21}" width="{x(s["recall"]) - left:.0f}" height="12" fill="#b3271d"/>')
        out.append(f'<text class="mut" x="{x(s["precision"]) + 6:.0f}" y="{y + 17}">P {s["precision"]:.2f}</text>')
        out.append(f'<text class="mut" x="{x(s["recall"]) + 6:.0f}" y="{y + 32}">R {s["recall"]:.2f}</text>')
    out.append(f'<rect x="{w - 170}" y="34" width="10" height="10" fill="#17130f"/>'
               f'<text class="mut" x="{w - 155}" y="43">precision</text>'
               f'<rect x="{w - 80}" y="34" width="10" height="10" fill="#b3271d"/>'
               f'<text class="mut" x="{w - 65}" y="43">recall</text>')
    out.append("</svg>")
    return "\n".join(out)


def report(s: dict) -> str:
    names = {"v1": "Unstale v1 (every channel member read every message)", "strong": "Interactions only",
             "digest": "Daily changelog of changes in your scope", "learned-noFB": "Unstale, learned from echoes only",
             "learned": "**Unstale (learned exposure)**", "ceiling": "Same model with the true hidden read rates"}
    lines = [f"# Benchmark: {s['orgs']} generated orgs x {s['sprints_per_org']} sprints ({s['backend']})", "",
             f"{s['messages']:,} messages, {s['people']} people and agents, {s['briefs_per_method']:,} briefs per method, "
             f"threshold {s['threshold']}, {int(s['response_rate'] * 100)}% of corrections answered.", "",
             "| Method | Precision | Recall | F1 | False alarms per 100 briefs |", "|---|---|---|---|---|"]
    for m in ["learned", "learned-noFB", "v1", "strong", "digest", "ceiling"]:
        t = s["total"][m]
        lines.append(f"| {names[m]} | {t['precision']:.2f} | {t['recall']:.2f} | {t['f1']:.2f} | "
                     f"{t['false_alarms_per_100_briefs']} |")
    lines += ["", "By sprint (F1):", "", "| Method | " + " | ".join(f"Sprint {i + 1}" for i in range(s["sprints_per_org"])) + " |",
              "|---|" + "---|" * s["sprints_per_org"]]
    for m in ["learned", "v1"]:
        lines.append(f"| {names[m]} | " + " | ".join(f"{c['f1']:.2f}" for c in s["by_sprint"][m]) + " |")
    lines += ["", "The last sprint, scored again with evidence from only the first n sprints:", "",
              "| Prior sprints of evidence | Precision | Recall | F1 | False alarms per 100 briefs |", "|---|---|---|---|---|"]
    for n, t in enumerate(s["same_sprint_after_n_prior_sprints"]):
        lines.append(f"| {n} | {t['precision']:.2f} | {t['recall']:.2f} | {t['f1']:.2f} | {t['false_alarms_per_100_briefs']} |")
    lines += ["", "Calibration of the learned model (every candidate it scored):", "",
              "| Predicted chance stale | Candidates | Actually stale |", "|---|---|---|"]
    for c in s["calibration"]:
        lines.append(f"| {c['bucket']} | {c['n']} | {c['rate']:.2f} |")
    return "\n".join(lines) + "\n"


def bootstrap_curve(rows: list[dict], sprints: int, boot: int = 2000, seed: int = 7) -> dict:
    """The same last sprint scored with n prior sprints of evidence, with 95% intervals from resampling orgs.

    Each org is a unit, so the intervals say how much the curve moves from org to org. The paired delta
    compares n = max with n = 0 on the same resampled orgs.
    """
    rng = random.Random(seed)

    def stats(sample: list[dict], n: int) -> dict:
        t = defaultdict(int)
        for r in sample:
            for a, v in r["runs"][n].items():
                t[a] += v
        return prf(t)

    pts = []
    for n in range(sprints):
        base = stats(rows, n)
        fa, f1, pr = [], [], []
        for _ in range(boot):
            sample = [rows[rng.randrange(len(rows))] for _ in rows]
            st = stats(sample, n)
            fa.append(st["false_alarms_per_100_briefs"])
            f1.append(st["f1"])
            pr.append(st["precision"])
        for xs in (fa, f1, pr):
            xs.sort()
        ci = lambda xs: [xs[int(0.025 * boot)], xs[int(0.975 * boot) - 1]]  # noqa: E731
        pts.append({"prior_sprints": n, **base, "false_alarms_ci": ci(fa), "f1_ci": ci(f1), "precision_ci": ci(pr)})
    last = sprints - 1
    d_fa, d_f1, d_pr = [], [], []
    for _ in range(boot):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        a, b = stats(sample, 0), stats(sample, last)
        d_fa.append(b["false_alarms_per_100_briefs"] - a["false_alarms_per_100_briefs"])
        d_f1.append(b["f1"] - a["f1"])
        d_pr.append(b["precision"] - a["precision"])
    out = {}
    for name, xs in (("false_alarms_per_100_briefs", d_fa), ("f1", d_f1), ("precision", d_pr)):
        xs.sort()
        out[name] = {"mean": round(sum(xs) / boot, 3), "ci95": [round(xs[int(0.025 * boot)], 3), round(xs[int(0.975 * boot) - 1], 3)],
                     "orgs_improved": None}
    # Per org: did the last-prior-sprint score beat the zero-prior one?
    better = 0
    for r in rows:
        a, b = prf(r["runs"][0]), prf(r["runs"][last])
        better += b["false_alarms_per_100_briefs"] < a["false_alarms_per_100_briefs"]
    out["false_alarms_per_100_briefs"]["orgs_improved"] = better

    # The control: same answers on the same corrections, coin-flip verdicts. If learning came from noise or from
    # merely having more evidence, this curve would fall too.
    def stats_ctl(sample: list[dict], n: int) -> dict:
        t = defaultdict(int)
        for r in sample:
            for k2, v in r["runs_control"][n].items():
                t[k2] += v
        return prf(t)

    control = [{"prior_sprints": n, **stats_ctl(rows, n)} for n in range(sprints)]
    d_ctl, d_gap = [], []
    for _ in range(boot):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        c0, cl = stats_ctl(sample, 0), stats_ctl(sample, last)
        d_ctl.append(cl["false_alarms_per_100_briefs"] - c0["false_alarms_per_100_briefs"])
        d_gap.append(stats(sample, last)["false_alarms_per_100_briefs"] - cl["false_alarms_per_100_briefs"])
    d_ctl.sort()
    d_gap.sort()
    ci = lambda xs: [round(xs[int(0.025 * boot)], 3), round(xs[int(0.975 * boot) - 1], 3)]  # noqa: E731
    return {"orgs": len(rows), "bootstrap_resamples": boot, "curve": pts, "paired_delta_last_vs_zero": out,
            "control_coin_flip_feedback": {
                "curve": control,
                "false_alarms_delta_last_vs_zero": {"mean": round(sum(d_ctl) / boot, 3), "ci95": ci(d_ctl)},
                "real_minus_control_false_alarms_at_last": {"mean": round(sum(d_gap) / boot, 3), "ci95": ci(d_gap)}}}


async def parity(seeds: list[int], sprints: int, threshold: float) -> bool:
    """HydraDB and the Python twin must produce the same briefs."""
    ok = True
    for seed in seeds:
        ds = orgsim.generate(seed, sprints)
        twin, graph = TwinBackend(ds), GraphBackend(ds, f"parity-{seed:03d}-{int(time.time())}")
        await twin.ingest()
        await graph.ingest()
        ev_t, ev_g = sorted(map(repr, await twin.implicit())), sorted(map(repr, await graph.implicit()))
        if ev_t != ev_g:
            print(f"  seed {seed}: evidence differs ({len(ev_t)} vs {len(ev_g)})")
            ok = False
        n = diff = 0
        for cp in mornings(ds["start"], ds["end"]):
            model = ReadModel([e for e in await twin.implicit() if e.ts <= cp])
            for p in ds["people"]:
                a = await brief(twin, p["id"], cp, await twin.exposures(p["id"], cp), model, threshold)
                b = await brief(graph, p["id"], cp, await graph.exposures(p["id"], cp), model, threshold)
                n += 1
                if sorted((x[0], x[1], round(x[3], 6)) for x in a) != sorted((x[0], x[1], round(x[3], 6)) for x in b):
                    diff += 1
                    if diff <= 3:
                        print(f"  seed {seed} {cp} {p['id']}: twin {a} vs graph {b}")
        print(f"parity seed {seed}: {n} briefs, {diff} differ; evidence {len(ev_t)} items")
        ok = ok and diff == 0
        await graph.close()
    return ok


async def main_async(a) -> None:
    if a.parity:
        ok = await parity(list(range(1, a.parity + 1)), a.sprints, a.threshold)
        print("PARITY OK" if ok else "PARITY FAILED")
        return
    backend = "hydradb" if a.hydradb else "twin"
    rows = []
    t0 = time.perf_counter()
    for seed in range(a.first, a.first + a.orgs):
        r = await run_org(seed, a.sprints, a.threshold, backend, "bench")
        rows.append(r)
        t = prf(r["totals"]["learned"])
        v = prf(r["totals"]["v1"])
        print(f"org {seed:03d}: {r['messages']} msgs, learned F1 {t['f1']:.2f} (P {t['precision']:.2f} R {t['recall']:.2f}) "
              f"vs v1 F1 {v['f1']:.2f}; ingest {r['ingest_s']}s; {time.perf_counter() - t0:.0f}s total", flush=True)
    if a.curve:
        c = bootstrap_curve(rows, a.sprints)
        c["command"] = f"python scripts/bench.py --first {a.first} --orgs {a.orgs} --sprints {a.sprints} --curve"
        OUT.mkdir(exist_ok=True)
        (OUT / "curve-twin.json").write_text(json.dumps(c, indent=1), encoding="utf-8")
        for pt in c["curve"]:
            print(f"n={pt['prior_sprints']}: false alarms {pt['false_alarms_per_100_briefs']} {pt['false_alarms_ci']}, "
                  f"F1 {pt['f1']} {pt['f1_ci']}, P {pt['precision']}")
        print(json.dumps(c["paired_delta_last_vs_zero"]))
        for pt in c["control_coin_flip_feedback"]["curve"]:
            print(f"control n={pt['prior_sprints']}: false alarms {pt['false_alarms_per_100_briefs']}, F1 {pt['f1']}, P {pt['precision']}")
        print(json.dumps({k: v for k, v in c["control_coin_flip_feedback"].items() if k != "curve"}))
        return
    s = summarise(rows, a.sprints, a.threshold, "HydraDB" if a.hydradb else "Python twin, parity-checked against HydraDB")
    if a.no_write:
        print(report(s))
        return
    OUT.mkdir(exist_ok=True)
    tag = "hydradb" if a.hydradb else "twin"
    (OUT / f"bench-{tag}.json").write_text(json.dumps({"summary": s, "orgs": [{k: v for k, v in r.items() if k != "briefs"}
                                                                               for r in rows]}, indent=1), encoding="utf-8")
    (OUT / f"BENCH-{tag}.md").write_text(report(s), encoding="utf-8")
    DOCS.mkdir(exist_ok=True)
    (DOCS / f"bench-{tag}.svg").write_text(chart(s), encoding="utf-8")
    print(report(s))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orgs", type=int, default=20)
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--sprints", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--hydradb", action="store_true")
    ap.add_argument("--parity", type=int, default=0, help="check N orgs on HydraDB against the twin")
    ap.add_argument("--curve", action="store_true", help="write eval/curve-twin.json (learning curve with intervals) only")
    ap.add_argument("--no-write", action="store_true", help="print the report without overwriting eval/ and docs/")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
