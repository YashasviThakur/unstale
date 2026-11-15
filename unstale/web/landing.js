"use strict";
/* Landing page: the hero video, and the results tables. The numbers come from
   /static/landing-data.json (scripts/landing_data.py writes it from the same result files the app's Proof panel reads),
   so the page never waits on the API. */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f2 = (x) => Number(x).toFixed(2);
const f1 = (x) => Number(x).toFixed(1);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---- the hero video (from Imprint): fades in when it plays, fades out before it ends, then loops ---- */
(function heroVideo() {
  const v = $("bgv");
  const saveData = navigator.connection && navigator.connection.saveData === true;
  if (!v || reduce || saveData) { if (v) v.remove(); return; }
  let raf = null;
  const fade = (to, ms) => {
    cancelAnimationFrame(raf);
    const from = parseFloat(v.style.opacity || "0"), t0 = performance.now();
    const step = (now) => { const k = Math.min(1, (now - t0) / ms); v.style.opacity = String(from + (to - from) * k); if (k < 1) raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
  };
  const play = () => v.play().catch(() => {});
  v.addEventListener("playing", () => fade(1, 400));
  v.addEventListener("timeupdate", () => { if (v.duration - v.currentTime <= 0.55 && parseFloat(v.style.opacity || "1") > 0.01) fade(0, 400); });
  v.addEventListener("ended", () => { cancelAnimationFrame(raf); v.style.opacity = "0"; setTimeout(() => { v.currentTime = 0; play(); }, 100); });
  play();
})();

/* ---- results ---- */
function curveSvg(c) {
  const pts = c.curve, W = 560, H = 250, L = 46, R = 20, T = 20, B = 48;
  const lo = Math.floor(Math.min(...pts.map((p) => p.false_alarms_ci[0])) / 5) * 5;
  const hi = Math.ceil(Math.max(...pts.map((p) => p.false_alarms_ci[1])) / 5) * 5;
  const x = (n) => L + (n / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const band = pts.map((p, k) => `${x(k)},${y(p.false_alarms_ci[1])}`).join(" ") + " " +
    [...pts].reverse().map((p, k) => `${x(pts.length - 1 - k)},${y(p.false_alarms_ci[0])}`).join(" ");
  const line = pts.map((p, k) => `${k ? "L" : "M"}${x(k)},${y(p.false_alarms_per_100_briefs)}`).join(" ");
  let grid = "";
  for (let v = lo; v <= hi; v += 5) grid += `<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const base = pts[0].false_alarms_per_100_briefs;
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="False alarms per 100 briefs fall as the graph learns from more sprints">
    ${grid}<polygon class="cband" points="${band}"/><line class="cbase" x1="${L}" x2="${W - R}" y1="${y(base)}" y2="${y(base)}"/>
    <path class="cline" d="${line}"/>
    ${pts.map((p, k) => `<circle class="cdot" cx="${x(k)}" cy="${y(p.false_alarms_per_100_briefs)}" r="4"/><text class="cval" x="${x(k)}" y="${y(p.false_alarms_per_100_briefs) - 10}" text-anchor="middle">${p.false_alarms_per_100_briefs}</text><text class="ct" x="${x(k)}" y="${H - 26}" text-anchor="middle">${k}</text>`).join("")}
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">sprints of evidence the graph has learned from</text></svg>`;
}

function results(P) {
  const nw = P.northwind, B = P.bench, T = B.total, cv = P.curve, bl = nw.baselines, un = nw.unstale;
  const row = (name, v, extra, us) => `<tr class="${us ? "us" : ""}"><td>${esc(name)}</td><td class="num">${f2(v)}</td><td class="fa">${extra}</td></tr>`;
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
  $("curve-card").innerHTML = `<h3>It improves with use.</h3>
    <p>On ${cv.orgs} generated orgs the engine had never seen, the same final sprint is scored again with evidence from only the first <i>n</i> sprints. False alarms per 100 briefs fall from <b>${first.false_alarms_per_100_briefs}</b> with no prior evidence to <b>${last.false_alarms_per_100_briefs}</b> with four sprints of it.</p>
    ${curveSvg(cv)}
    <p>The paired change is <b>${f1(d.false_alarms_per_100_briefs.mean)}</b> (95% interval ${d.false_alarms_per_100_briefs.ci95.map(f1).join(" to ")}), and <b>${d.false_alarms_per_100_briefs.orgs_improved} of ${cv.orgs}</b> orgs improved. F1 moves less (+${d.f1.mean.toFixed(3)}): learning removes false alarms, while recall is capped by beliefs nothing observable reveals.</p>`;
}

fetch("/static/landing-data.json").then((r) => r.json()).then((d) => results(d.proof))
  .catch(() => { $("ledger").innerHTML = `<p class="dim">The results couldn't load. <a href="/app?proof=1&notour=1">Open them in the app</a>.</p>`; });
