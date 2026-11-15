"use strict";
/* Fills the proof ledger from the same result files the app's Proof panel reads. */

const f2 = (x) => Number(x).toFixed(2);
const f1 = (x) => Number(x).toFixed(1);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function curveSvg(c) {
  const pts = c.curve, W = 560, H = 250, L = 46, R = 20, T = 20, B = 48;
  const lo = Math.floor(Math.min(...pts.map((p) => p.false_alarms_ci[0])) / 5) * 5;
  const hi = Math.ceil(Math.max(...pts.map((p) => p.false_alarms_ci[1])) / 5) * 5;
  const x = (n) => L + (n / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const band = pts.map((p, i) => `${x(i)},${y(p.false_alarms_ci[1])}`).join(" ") + " " +
    [...pts].reverse().map((p, i) => `${x(pts.length - 1 - i)},${y(p.false_alarms_ci[0])}`).join(" ");
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.false_alarms_per_100_briefs)}`).join(" ");
  let grid = "";
  for (let v = lo; v <= hi; v += 5) grid += `<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const base = pts[0].false_alarms_per_100_briefs;
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="False alarms per 100 briefs fall as the graph learns from more sprints">
    ${grid}<polygon class="cband" points="${band}"/>
    <line class="cbase" x1="${L}" x2="${W - R}" y1="${y(base)}" y2="${y(base)}"/>
    <path class="cline" d="${line}"/>
    ${pts.map((p, i) => `<circle class="cdot" cx="${x(i)}" cy="${y(p.false_alarms_per_100_briefs)}" r="4"/>
      <text class="cval" x="${x(i)}" y="${y(p.false_alarms_per_100_briefs) - 10}" text-anchor="middle">${p.false_alarms_per_100_briefs}</text>
      <text class="ct" x="${x(i)}" y="${H - 26}" text-anchor="middle">${i}</text>`).join("")}
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">sprints of evidence the graph has learned from</text></svg>`;
}

async function fill() {
  let P;
  try { P = await (await fetch("/api/proof")).json(); } catch (e) { return; }
  const nw = P.northwind, B = P.bench, T = B.total, cv = P.curve;
  const row = (name, f1v, extra, us) => `<tr class="${us ? "us" : ""}"><td>${esc(name)}</td>
    <td><span class="bar"><i style="width:${Math.max(1, f1v * 100)}%"></i></span><span class="num">${f2(f1v)}</span></td><td class="fa">${extra}</td></tr>`;
  const bl = nw.baselines, un = nw.unstale;
  $("ledger").innerHTML = `
    <table><thead><tr><th>A hand-labelled team (80 briefs)</th><th>F1</th><th>LLM tokens per brief</th></tr></thead><tbody>
      ${row("Unstale", un.f1, "0", true)}
      ${row("An LLM given every message and every member list", bl.org_llm.f1, bl.org_llm.tokens_per_brief.toLocaleString())}
      ${row("Vector RAG over the messages", bl.vector_rag.f1, bl.vector_rag.tokens_per_brief.toLocaleString())}
      ${row("A recap of the person's own channels", bl.recap.f1, bl.recap.tokens_per_brief.toLocaleString())}
    </tbody></table>
    <table><thead><tr><th>${B.orgs} generated orgs with hidden reading habits (${B.briefs_per_method.toLocaleString()} briefs per method)</th><th>F1</th><th>False alarms per 100 briefs</th></tr></thead><tbody>
      ${row("Unstale, learning from feedback", T.learned.f1, T.learned.false_alarms_per_100_briefs, true)}
      ${row("Assume everyone in the channel read it", T.v1.f1, T.v1.false_alarms_per_100_briefs)}
      ${row("Count only interactions", T.strong.f1, T.strong.false_alarms_per_100_briefs)}
      ${row("A daily changelog of changes in your scope", T.digest.f1, T.digest.false_alarms_per_100_briefs)}
    </tbody></table>`;
  const d = cv.paired_delta_last_vs_zero, last = cv.curve[cv.curve.length - 1], first = cv.curve[0];
  $("curve-card").innerHTML = `<div><h3>It gets sharper every run.</h3>
      <p>On ${cv.orgs} orgs the engine had never seen, the same final sprint is scored again with evidence from only the first <i>n</i> sprints. False alarms per 100 briefs fall from <b>${first.false_alarms_per_100_briefs}</b> to <b>${last.false_alarms_per_100_briefs}</b>.</p>
      <p>Paired change <b>${f1(d.false_alarms_per_100_briefs.mean)}</b> (95% interval ${d.false_alarms_per_100_briefs.ci95.map(f1).join(" to ")}); <b>${d.false_alarms_per_100_briefs.orgs_improved} of ${cv.orgs}</b> orgs improved. F1 moves less (+${d.f1.mean.toFixed(3)}): learning removes false alarms, while recall is capped by beliefs nothing observable reveals.</p></div>
    <div>${curveSvg(cv)}</div>`;
  fillDays(P);
}

function frontierSvg(F) {
  const W = 560, H = 250, L = 46, R = 20, T = 20, B = 48, pts = F.points, d = pts[0].digest;
  const xmax = 120, ylo = 40, yhi = 100;
  const x = (v) => L + (v / xmax) * (W - L - R), y = (v) => T + (1 - (v - ylo) / (yhi - ylo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.learned.false_alarms_per_100_briefs)},${y(p.learned.stale_days_removed * 100)}`).join(" ");
  let grid = "";
  for (let v = ylo; v <= yhi; v += 20) grid += `<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  for (let v = 0; v <= xmax; v += 20) grid += `<text class="ct" x="${x(v)}" y="${H - 26}" text-anchor="middle">${v}</text>`;
  const def = pts.find((p) => p.threshold === 0.5);
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="Stale person-days removed against false alarms per 100 briefs">
    ${grid}<path class="cline" d="${line}"/>
    ${pts.map((p) => `<circle class="cdot" cx="${x(p.learned.false_alarms_per_100_briefs)}" cy="${y(p.learned.stale_days_removed * 100)}" r="${p === def ? 6 : 3.5}"/>`).join("")}
    <text class="ct" x="${x(def.learned.false_alarms_per_100_briefs) + 12}" y="${y(def.learned.stale_days_removed * 100) + 22}">Unstale, default</text>
    <circle cx="${x(d.false_alarms_per_100_briefs)}" cy="${y(d.stale_days_removed * 100)}" r="7" fill="#e07a3f"/>
    <text class="ct" x="${x(d.false_alarms_per_100_briefs) - 10}" y="${y(d.stale_days_removed * 100) + 24}" text-anchor="end">daily changelog</text>
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">false alarms per 100 briefs (lower is better)</text></svg>`;
}

function fillDays(P) {
  const F = P.frontier;
  if (!F || !F.points) return;
  const def = F.points.find((p) => p.threshold === 0.5), hi = F.points[0], dg = def.digest, v1 = def.v1;
  $("days-card").innerHTML = `<div><h3>And it removes the stale days.</h3>
      <p>A stale person-day is one person holding one outdated fact for one morning. Acting on Unstale's default briefs removes <b>${Math.round(def.learned.stale_days_removed * 100)}%</b> of them, at <b>${def.learned.false_alarms_per_100_briefs}</b> false alarms per 100 briefs. The most sensitive setting removes <b>${Math.round(hi.learned.stale_days_removed * 100)}%</b> at ${hi.learned.false_alarms_per_100_briefs}.</p>
      <p>A daily changelog removes ${Math.round(dg.stale_days_removed * 100)}%, because it tells everyone, at <b>${dg.false_alarms_per_100_briefs}</b>. The engine that assumed everyone in a channel read it removes the same ${Math.round(v1.stale_days_removed * 100)}% as Unstale at ${v1.false_alarms_per_100_briefs}: learning who reads what is what removes the noise.</p></div>
    <div>${frontierSvg(F)}</div>`;
}
const $ = (id) => document.getElementById(id);
fill();
