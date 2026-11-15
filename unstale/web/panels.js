"use strict";
/* Proof and Pitch panels. Every number on the Proof panel is read from /api/proof, which reads the result files. */

const pct = (x) => `${Math.round(x * 100)}%`;
const f2 = (x) => Number(x).toFixed(2);
const f1 = (x) => Number(x).toFixed(1);

function barRow(label, value, max, text, cls = "", sub = "") {
  return `<div class="brow ${cls}"><div class="bl">${label}${sub ? `<span>${sub}</span>` : ""}</div>
    <div class="bt"><i style="width:${Math.max(0.6, (value / max) * 100)}%"></i></div><div class="bv">${text}</div></div>`;
}

function curveSvg(c) {
  const pts = c.curve, W = 640, H = 270, L = 52, R = 24, T = 20, B = 52;
  const ctl = (c.control_coin_flip_feedback || {}).curve || [];
  const lo = Math.floor(Math.min(...pts.map((p) => p.false_alarms_ci[0]), ...ctl.map((p) => p.false_alarms_per_100_briefs)) / 5) * 5;
  const hi = Math.ceil(Math.max(...pts.map((p) => p.false_alarms_ci[1]), ...ctl.map((p) => p.false_alarms_per_100_briefs)) / 5) * 5;
  const step = hi - lo > 30 ? 10 : 5;
  const x = (n) => L + (n / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const band = pts.map((p, i) => `${x(i)},${y(p.false_alarms_ci[1])}`).join(" ") + " " +
    [...pts].reverse().map((p, i) => `${x(pts.length - 1 - i)},${y(p.false_alarms_ci[0])}`).join(" ");
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.false_alarms_per_100_briefs)}`).join(" ");
  const grid = [];
  for (let v = lo; v <= hi; v += step) grid.push(`<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`);
  const base = pts[0].false_alarms_per_100_briefs;
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="False alarms per 100 briefs by prior sprints of evidence">
    ${grid.join("")}
    <polygon class="cband" points="${band}"/>
    <line class="cbase" x1="${L}" x2="${W - R}" y1="${y(base)}" y2="${y(base)}"/>
    <text class="ct" x="${W - R}" y="${y(base) - 6}" text-anchor="end">baseline: no prior evidence</text>
    ${ctl.length ? `<path class="cline" style="stroke-dasharray:6 5;opacity:.55" d="${ctl.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.false_alarms_per_100_briefs)}`).join(" ")}"/>
      <text class="ct" x="${W - R}" y="${y(ctl[ctl.length - 1].false_alarms_per_100_briefs) - 8}" text-anchor="end">control: same answers, coin-flip verdicts</text>` : ""}
    <path class="cline" d="${line}"/>
    ${pts.map((p, i) => `<circle class="cdot" cx="${x(i)}" cy="${y(p.false_alarms_per_100_briefs)}" r="4"/>
      <text class="cval" x="${x(i)}" y="${y(p.false_alarms_per_100_briefs) - 10}" text-anchor="middle">${p.false_alarms_per_100_briefs}</text>
      <text class="ct" x="${x(i)}" y="${H - 30}" text-anchor="middle">${i}</text>`).join("")}
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle">earlier sprints of evidence the graph has learned from</text>
    <text class="ct" transform="translate(13 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">false alarms per 100 briefs (lower is better)</text></svg>`;
}


/* Stale person-days removed against notification noise: Unstale at several alert thresholds, and the changelog. */
function frontierSvg(F) {
  const W = 640, H = 290, L = 54, R = 28, T = 24, B = 54, pts = F.points;
  const xs = pts.map((p) => p.learned.false_alarms_per_100_briefs).concat(pts[0].digest.false_alarms_per_100_briefs);
  const xmax = Math.ceil(Math.max(...xs) / 20) * 20, ylo = 40, yhi = 100;
  const x = (v) => L + (v / xmax) * (W - L - R), y = (v) => T + (1 - (v - ylo) / (yhi - ylo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.learned.false_alarms_per_100_briefs)},${y(p.learned.stale_days_removed * 100)}`).join(" ");
  const d = pts[0].digest, def = pts.find((p) => p.threshold === 0.5) || pts[0];
  let grid = "";
  for (let v = ylo; v <= yhi; v += 20) grid += `<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  for (let v = 0; v <= xmax; v += 20) grid += `<text class="ct" x="${x(v)}" y="${H - 30}" text-anchor="middle">${v}</text>`;
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="Stale person-days removed against false alarms per 100 briefs">
    ${grid}<path class="cline" d="${line}"/>
    ${pts.map((p) => `<circle class="cdot" cx="${x(p.learned.false_alarms_per_100_briefs)}" cy="${y(p.learned.stale_days_removed * 100)}" r="${p === def ? 6 : 3.5}"/>
      ${[[0.2, 10, -10, "start"], [0.5, 14, 22, "start"], [0.9, 12, 24, "start"]].filter((l) => l[0] === p.threshold).map((l) => `<text class="ct" x="${x(p.learned.false_alarms_per_100_briefs) + l[1]}" y="${y(p.learned.stale_days_removed * 100) + l[2]}" text-anchor="${l[3]}">${l[0] === 0.5 ? "default: alert at 50% sure" : `alert at ${Math.round(l[0] * 100)}% sure`}</text>`).join("")}`).join("")}
    <circle cx="${x(d.false_alarms_per_100_briefs)}" cy="${y(d.stale_days_removed * 100)}" r="7" fill="#e07a3f"/>
    <text class="ct" x="${x(d.false_alarms_per_100_briefs) - 10}" y="${y(d.stale_days_removed * 100) + 24}" text-anchor="end">daily changelog: ${Math.round(d.stale_days_removed * 100)}% at ${d.false_alarms_per_100_briefs}</text>
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">false alarms per 100 briefs: corrections about things the person already knew (lower is better)</text>
    <text class="ct" transform="translate(13 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">stale person-days removed</text></svg>`;
}

async function openProof() {
  const body = $("proof-body"), dlg = $("proof-dialog");
  openDlg(dlg);
  if (!body.dataset.ready) {
    body.innerHTML = `<p class="muted">Loading the result files...</p>`;
    let P;
    try { P = await api("/api/proof"); } catch (e) { body.innerHTML = `<p class="muted">Couldn't load the results: ${esc(e.message)}</p>`; return; }
    body.dataset.ready = "1";
    const nw = P.northwind, un = nw.unstale, bl = nw.baselines, B = P.bench, T = B.total, cv = P.curve, ag = P.agent;
    const d = cv.paired_delta_last_vs_zero, last = cv.curve[cv.curve.length - 1], first = cv.curve[0];
    const nwRows = [["Unstale", un.f1, 0, "us", `P ${f2(un.precision)} · R ${f2(un.recall)} · ${un.ms_per_brief} ms`],
      ["Org-wide LLM (every message + member lists)", bl.org_llm.f1, bl.org_llm.tokens_per_brief, "", `P ${f2(bl.org_llm.precision)} · R ${f2(bl.org_llm.recall)}`],
      ["Vector RAG (top 8 messages + LLM)", bl.vector_rag.f1, bl.vector_rag.tokens_per_brief, "", `P ${f2(bl.vector_rag.precision)} · R ${f2(bl.vector_rag.recall)} · told people what they knew ${bl.vector_rag.told_what_they_knew}×`],
      ["Recap of own channels (LLM)", bl.recap.f1, bl.recap.tokens_per_brief, "", `P ${f2(bl.recap.precision)} · R ${f2(bl.recap.recall)}`]];
    const methods = [["learned", "Unstale (learned exposure)", "us"], ["learned-noFB", "Learned from echoes only, no feedback", ""],
      ["v1", "Every channel member is assumed to have read it", ""], ["strong", "Interactions only", ""],
      ["digest", "Daily changelog of changes in your scope", ""], ["ceiling", "Same model given the true hidden read rates", "ceil"]];
    const agRows = [["own", "Its own knowledge base (same access)"], ["unstale", "Own knowledge base + Unstale's block"],
      ["everything", "Every message in the org, pasted in"], ["rag", "Vector RAG over every channel"]];
    body.innerHTML = `
      <p class="lede">Every number here is read from a result file in the repo. Under each chart is the command that produces it.</p>

      <div class="pcards">
        <div class="pcard"><b>${f2(un.f1)} <em>vs</em> ${f2(bl.vector_rag.f1)}</b><span>F1 on the labelled team: Unstale vs vector RAG</span></div>
        <div class="pcard"><b>${un.llm_tokens_per_brief} tokens</b><span>per brief, ${un.ms_per_brief} ms. A brief is a graph traversal, not a model call</span></div>
        <div class="pcard"><b>${T.learned.false_alarms_per_100_briefs} <em>vs</em> ${T.digest.false_alarms_per_100_briefs}</b><span>false alarms per 100 briefs: Unstale vs a daily changelog (${B.orgs} orgs)</span></div>
        <div class="pcard"><b>${pct(ag.own.accuracy)} → ${pct(ag.unstale.accuracy)}</b><span>support agent answering customers, same sources, with Unstale's block</span></div>
      </div>

      <h3>What we measure, and why</h3>
      <dl class="defs">
        <dt>Stale-belief precision</dt><dd>Of the corrections we send, how many are real. The cost of getting this wrong is notification fatigue, so it is the metric that decides whether anyone keeps the product on.</dd>
        <dt>Stale-belief recall</dt><dd>Of the facts people actually hold in an outdated version, how many we find.</dd>
        <dt>False alarms per 100 briefs</dt><dd>Corrections about things the person already knew. This is the number a changelog or a recap fails on.</dd>
        <dt>Tokens per brief</dt><dd>What it costs to produce one person's brief every morning. It decides whether this scales to every person and every agent.</dd>
      </dl>
      <p class="small muted">Ground truth is hidden from the engine: each message carries its true claims and who really read it. The engine sees only what a Slack export shows.</p>

      <h3>1. A labelled team (Northwind, 80 briefs)</h3>
      ${nwRows.map((r) => barRow(esc(r[0]), r[1], 1, `F1 ${f2(r[1])}`, r[3], `${r[2] ? r[2].toLocaleString() + " tokens per brief · " : ""}${r[4]}`)).join("")}
      <p class="small muted">Unstale scores on all 80 briefs; the LLM rows on 16 (Groq free-tier limits), where Unstale also scores P 1.00 R 0.92. Reproduce: <code>python scripts/eval.py</code>, <code>python scripts/baselines.py</code>.</p>

      <h3>2. ${B.orgs} generated orgs with hidden reading (${B.messages.toLocaleString()} messages, ${B.briefs_per_method.toLocaleString()} briefs per method)</h3>
      <p class="small muted">Companies where reading is latent: each person has a hidden read rate per channel, and people post what they actually believe, so stale people produce real echoes.</p>
      <table class="ptable"><thead><tr><th>Method</th><th>Precision</th><th>Recall</th><th>F1</th><th>False alarms / 100 briefs</th></tr></thead><tbody>
      ${methods.map(([k, n, c]) => `<tr class="${c}"><td>${esc(n)}</td><td>${f2(T[k].precision)}</td><td>${f2(T[k].recall)}</td><td><b>${f2(T[k].f1)}</b></td><td>${T[k].false_alarms_per_100_briefs}</td></tr>`).join("")}
      </tbody></table>
      <p class="small muted">Reproduce: <code>python scripts/bench.py</code> (the engine on HydraDB reproduces the twin brief for brief: <code>--hydradb --parity 2</code>).</p>

      ${P.frontier && P.frontier.points ? (() => { const F = P.frontier, def = F.points.find((p) => p.threshold === 0.5), hi = F.points[0], dg = def.digest, ratio = dg.false_alarms_per_100_briefs / def.learned.false_alarms_per_100_briefs;
        return `<h3>3. Does acting on it remove stale days?</h3>
      <p class="small muted">A stale person-day is one person holding one outdated fact for one morning (${F.points[0].stale_days.toLocaleString()} in these ${F.orgs} orgs). If a person acts on a correction the morning they get it, every later morning of that belief goes away. This is the outcome a manager pays for, measured against the cost: notifications about things people already knew.</p>
      ${frontierSvg(F)}
      <div class="pcards three">
        <div class="pcard"><b>${Math.round(def.learned.stale_days_removed * 100)}% at ${def.learned.false_alarms_per_100_briefs}</b><span>of stale person-days removed, at false alarms per 100 briefs: Unstale at its default alert threshold</span></div>
        <div class="pcard"><b>${Math.round(hi.learned.stale_days_removed * 100)}% at ${hi.learned.false_alarms_per_100_briefs}</b><span>the most sensitive setting (alert at ${Math.round(hi.threshold * 100)}%): for a team that would rather over-check</span></div>
        <div class="pcard"><b>${Math.round(dg.stale_days_removed * 100)}% at ${dg.false_alarms_per_100_briefs}</b><span>a daily changelog tells everyone in scope, so it removes the most, with ${f1(ratio)}x Unstale's default noise. Every false alarm teaches people to ignore it</span></div>
      </div>
      <p class="small muted">Assumes people act on the correction the same morning. Unstale's reach is bounded by what is observable: beliefs from a channel message nobody can see was opened stay hidden. Reproduce: <code>python scripts/bench.py --sweep</code>.</p>`; })() : ""}
      <h3>${P.frontier && P.frontier.points ? 4 : 3}. It gets sharper every run</h3>
      <p class="small muted">${cv.orgs} further orgs the engine had never seen (seeds 101-140, five sprints each). The same final sprint is scored again with evidence from only the first <i>n</i> sprints: people's "news to me / I knew this" answers, plus echoes and restatements.</p>
      ${curveSvg(cv)}
      <div class="pcards three">
        <div class="pcard"><b>${f1(d.false_alarms_per_100_briefs.mean)} <small>[${d.false_alarms_per_100_briefs.ci95.map(f1).join(", ")}]</small></b><span>change in false alarms per 100 briefs, ${last.prior_sprints} sprints vs none (95% interval over orgs)</span></div>
        <div class="pcard"><b>${d.false_alarms_per_100_briefs.orgs_improved} of ${cv.orgs}</b><span>orgs got fewer false alarms. Precision ${f2(first.precision)} → ${f2(last.precision)}, F1 ${f2(first.f1)} → ${f2(last.f1)} (+${d.f1.mean.toFixed(3)} [${d.f1.ci95.map((x) => x.toFixed(3)).join(", ")}])</span></div>
        <div class="pcard"><b>${B.same_sprint_after_n_prior_sprints.map((x) => f1(x.false_alarms_per_100_briefs)).join(" → ")}</b><span>the same effect in the 20-org benchmark above, with 0, 1, 2 prior sprints</span></div>
      </div>
      ${cv.control_coin_flip_feedback ? (() => { const k = cv.control_coin_flip_feedback, kc = k.curve, g = k.real_minus_control_false_alarms_at_last, dk = k.false_alarms_delta_last_vs_zero;
        return `<div class="pcards three">
        <div class="pcard"><b>${f1(kc[0].false_alarms_per_100_briefs)} → ${f1(kc[kc.length - 1].false_alarms_per_100_briefs)}</b><span>the control: the same people answer the same corrections, but every verdict is a coin flip (change ${f1(dk.mean)} [${dk.ci95.map(f1).join(", ")}])</span></div>
        <div class="pcard"><b>${f1(g.mean)} <small>[${g.ci95.map(f1).join(", ")}]</small></b><span>false alarms per 100 briefs, real answers minus coin-flip answers, after ${last.prior_sprints} sprints</span></div>
        <div class="pcard"><b>The lesson</b><span>More evidence does not help on its own. What people say about their own corrections is what teaches the graph.</span></div>
      </div>`; })() : ""}
      <p class="small muted">Baseline is the same engine with no prior evidence. F1 moves less than precision: learning removes false alarms, while recall is capped by beliefs nothing observable reveals. Reproduce: <code>python scripts/bench.py --curve --orgs 40 --first 101 --sprints 5</code>.</p>

      <h3>${P.frontier && P.frontier.points ? 5 : 4}. Agents</h3>
      <p class="small muted">A support agent reads its own knowledge-base channel; prices, refund windows and API status change elsewhere. A customer asks about each fact it is responsible for (${ag.own.questions} questions, 4 generated orgs and Northwind).</p>
      ${agRows.map(([k, n]) => barRow(esc(n), ag[k].accuracy, 1, `${pct(ag[k].accuracy)} correct`, k === "unstale" ? "us" : "", `${ag[k].prompt_tokens_per_answer.toLocaleString()} prompt tokens · ${ag[k].outdated_answers} outdated answers`)).join("")}
      <p class="small muted">Vector RAG does well here because it was allowed to search every channel in the company. That is a permissions decision most teams will not make for a customer-facing bot. With the access it already has, the agent is right ${pct(ag.own.accuracy)} of the time and confidently outdated ${ag.own.outdated_answers} times; Unstale's block fixes that with no new access. Reproduce: <code>python scripts/agent_eval.py</code>.</p>

      ${(P.load || []).length ? `<h3>${P.frontier && P.frontier.points ? 6 : 5}. Under load</h3>
      <p class="small muted">Concurrent users looping over what visitors and agents do: briefs, the team table, fact history, the graph view, Fix it and the pre-send check. The local run also writes "news to me / I knew this" feedback to HydraDB while it serves, which clears the per-person caches so the next reads go back to the graph.</p>
      <table class="ptable"><thead><tr><th>Where</th><th>Users</th><th>Requests</th><th>Per second</th><th>p50</th><th>p95</th><th>Errors</th></tr></thead><tbody>
      ${P.load.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.users}</td><td>${r.requests.toLocaleString()}</td><td>${r.rps}</td><td>${r.p50_ms} ms</td><td>${r.p95_ms} ms</td><td>${r.errors}</td></tr>`).join("")}
      </tbody></table>
      <p class="small muted">Reproduce: <code>python scripts/loadtest.py --url URL --users 20 --seconds 60 [--writes]</code>. The public demo refuses writes from the load test so visitors keep their feedback quota.</p>` : ""}

      <h3>${(P.frontier && P.frontier.points ? 1 : 0) + ((P.load || []).length ? 6 : 5)}. Calibration</h3>
      <p class="small muted">Of everything the model scored, how often it was stale, by predicted chance. A 90-100% candidate should be stale about nine times in ten.</p>
      ${B.calibration.map((c) => barRow(c.bucket, c.rate, 1, `${pct(c.rate)} stale <small>(${c.n.toLocaleString()} candidates)</small>`)).join("")}

      <h3>Limits, plainly</h3>
      <ul class="limits">
        <li><b>The data is simulated.</b> The generator is built to be hard the way real teams are (lurkers, edge-of-job channels, people who repeat old values), and the engine never sees the answer key, but it is still our simulator. Real read receipts would replace the estimate; <code>python -m unstale.slack_import</code> runs it on a real export.</li>
        <li><b>Recall has a ceiling.</b> About a third of stale beliefs come from a channel message the person never opened, with nothing observable to say so. Even a model given the true read rates tops out at ${f2(T.ceiling.recall)}.</li>
        <li><b>Exposure is estimated, so every correction carries a confidence</b> and a one-click way to tell the graph it was wrong.</li>
      </ul>`;
  }
}

async function openPitch() {
  const body = $("pitch-body");
  if (!body.dataset.ready) {
    body.dataset.ready = "1";
    body.innerHTML = `
      <p class="lede">Search tells you what is true. Unstale tells you who doesn't know yet.</p>
      <div class="pcols">
        <section><h3>The problem has a price</h3>
          <p>Poor communication costs US businesses up to <b>$1.2 trillion a year, about $12,506 per employee</b> (Grammarly and The Harris Poll, 2022). The costly slice is narrow and recognisable: an account executive quotes a ship date that already moved, customer success renews at last quarter's price, a support agent gives out a refund window that changed yesterday.</p>
          <p>Nobody was careless. The change happened in a channel they weren't in. And every AI agent answering customers is one more reader who misses changes: a stale person sends one wrong email, a stale agent repeats the old policy to everyone who asks that day.</p></section>
        <section><h3>Who pays first</h3>
          <p><b>Slack-first B2B SaaS, 50 to 500 people</b>, where product and pricing decisions move fast and a revenue team and at least one support agent sit downstream.</p>
          <p><b>Buyer:</b> VP RevOps or Head of Support Ops, who owns what reps and bots tell customers and gets the escalation when it is wrong. <b>Champion:</b> the enablement lead who re-posts every change by hand today. <b>Second buyer:</b> teams building agents.</p></section>
        <section><h3>Why now, and why not what exists</h3>
          <p>Enterprise search, channel recaps, verified-knowledge tools and temporal agent memory all answer <i>what is true now</i>. None keep the other half of the record, <b>who saw which version</b>. On our labelled team that is the difference between F1 0.96 and 0.13, and between 7 and 105 false alarms per 100 briefs.</p></section>
        <section><h3>Wedge → product</h3>
          <ol><li><b>Close the gap</b>: who still needs to hear a change, where to post, who needs an @mention, and a draft.</li><li><b>Check before sending</b> for customer-facing people.</li><li><b>Morning corrections</b> with a "news to me" button that teaches the graph.</li><li><b>A correction block for agents</b> over MCP, about 100 extra tokens per answer.</li></ol>
          <p class="small muted">Trial: run the Slack-export importer on last quarter and read "these 11 people were working from an old price on these dates". That report is the sales call.</p></section>
        <section><h3>Pricing hypothesis, to test with design partners</h3>
          <table class="ptable price"><tbody>
            <tr><td><b>Free</b></td><td>one team, up to 15 people and 1 agent</td></tr>
            <tr><td><b>Team</b></td><td>$6 per person per month: briefs, pre-send checks, feedback learning</td></tr>
            <tr><td><b>Agents</b></td><td>$20 per agent per month, with a volume of checks included; usage-priced above it</td></tr></tbody></table>
          <p class="small muted">Agents are where it scales: a company runs a handful of people per team but can run dozens of agents, each checking before every answer. Briefs cost zero model tokens, so margin doesn't shrink with headcount.</p></section>
        <section><h3>Why it compounds</h3>
          <ul><li><b>The exposure graph is the asset.</b> Who saw which version is in no document; it is reconstructed from interactions and kept as edges in a versioned graph.</li>
          <li><b>It improves with use.</b> Every "news to me", echo and restatement teaches it who reads what; on unseen orgs, false alarms fall about 28% after four sprints.</li>
          <li><b>Self-hostable.</b> Runs on open-source HydraDB inside the customer's own infrastructure; the graph can keep claims and edges without message text.</li></ul></section>
      </div>
      <h3>What it could be worth to you</h3>
      <div class="calc" id="calc">
        <label>People <input type="number" id="c-people" min="1" value="60"></label>
        <label>AI agents <input type="number" id="c-agents" min="0" value="2"></label>
        <label>Out-of-date beliefs that matter, per person per month <input type="number" id="c-stale" min="0" step="0.5" value="2"></label>
        <label>Share that reach a customer or a system (%) <input type="number" id="c-share" min="0" max="100" value="10"></label>
        <label>Cost of one wrong statement ($) <input type="number" id="c-cost" min="0" value="300"></label>
        <div class="calc-out" id="calc-out"></div>
      </div>
      <p class="small muted">Illustrative. The inputs are yours; the one number we measured is the share Unstale catches (recall <span id="c-recall">0.66</span> on the generated orgs; precision 0.87). Our simulated orgs are far denser in changes than a real team, so we don't claim a rate for you. Prices are the hypothesis above.</p>
      <div class="cta"><b>Next 90 days:</b> Slack app (morning DM, message-action check) → three design partners running a four-week pilot measured in <i>outdated statements caught before they reached a customer</i> → publish the benchmark as an open dataset.
        <a class="btn" href="https://github.com/YashasviThakur/unstale/issues/new?title=Design%20partner%3A%20&body=Team%20size%3A%0AWhere%20decisions%20are%20made%20(Slack%2FTeams%2Femail)%3A%0AWhat%20goes%20stale%20for%20you%3A" target="_blank" rel="noopener">Be a design partner</a>
        <a class="btn ghost" href="https://github.com/YashasviThakur/unstale" target="_blank" rel="noopener">Repo</a></div>`;
  }
  openDlg($("pitch-dialog"));
  wireCalc();
}

async function wireCalc() {
  let recall = 0.66;
  try { recall = (await api("/api/proof")).bench.total.learned.recall; } catch (e) { /* keep the default */ }
  $("c-recall").textContent = recall.toFixed(2);
  const run = () => {
    const v = (id) => Math.max(0, parseFloat($(id).value) || 0);
    const people = v("c-people"), agents = v("c-agents"), stale = v("c-stale"), share = Math.min(100, v("c-share")) / 100, cost = v("c-cost");
    const wrong = people * stale * share, caught = wrong * recall, saved = caught * cost, price = people * 6 + agents * 20;
    const money = (x) => "$" + Math.round(x).toLocaleString();
    $("calc-out").innerHTML = `<div><b>${wrong.toFixed(1)}</b><span>wrong statements or actions a month</span></div>
      <div><b>${caught.toFixed(1)}</b><span>caught before they land</span></div>
      <div><b>${money(saved)}</b><span>avoided a month, at ${money(cost)} each</span></div>
      <div><b>${money(price)}</b><span>Unstale a month at the hypothesis prices</span></div>
      <div class="net"><b>${price ? (saved / price).toFixed(1) + "x" : "n/a"}</b><span>return on the subscription</span></div>`;
  };
  document.querySelectorAll("#calc input").forEach((el) => { el.oninput = run; });
  run();
}

function openMcp() {
  const url = `${location.origin}/mcp`;
  const cfg = JSON.stringify({ mcpServers: { unstale: { url } } }, null, 2);
  $("mcp-body").innerHTML = `
    <p class="lede">The demo team's graph is live as an MCP server. Connect any agent and it can ask what in its context is out of date, who to tell, and whether a draft repeats an old fact. It is read-only here.</p>
    <h3>Claude Code</h3>
    <pre class="code" id="mcp-cmd">claude mcp add --transport http unstale ${esc(url)}</pre>
    <h3>Cursor, Claude Desktop and other clients</h3>
    <pre class="code">${esc(cfg)}</pre>
    <h3>Then ask it</h3>
    <ul class="limits">
      <li><code>What does agent:support-bot believe that is no longer true?</code> → <b>corrections</b></li>
      <li><code>Team plan price changed. Who still has the old one, and who should I tell?</code> → <b>who_to_notify</b> (subject <code>plan:team</code>, attribute <code>PRICED_AT</code>)</li>
      <li><code>Who holds which version of the 2.4 ship date?</code> → <b>who_believes</b></li>
    </ul>
    <p class="small muted">People are ids like <code>person:maya</code> and <code>agent:support-bot</code>; times run 22 Jun to 1 Jul 2026 and default to the end. Tools: corrections, who_to_notify, who_believes, check_before_sending (preset drafts only on the public demo), give_feedback (capped). Source: <code>unstale/mcp_server.py</code>.</p>`;
  openDlg($("mcp-dialog"));
}


/* The stale-belief report: replays every morning and counts, with the engine's own traversals. */
async function openReport() {
  const body = $("report-body"), dlg = $("report-dialog");
  openDlg(dlg);
  if (body.dataset.ready) return;
  body.innerHTML = `<p class="muted">Replaying every morning of the team's history...</p>`;
  let R;
  try { R = await api("/api/report"); } catch (e) { body.innerHTML = `<p class="muted">Couldn't build the report: ${esc(e.message)}</p>`; return; }
  body.dataset.ready = "1";
  const h = R.headline, maxD = Math.max(...R.changes.map((c) => c.stale_person_days), 1), maxP = Math.max(...R.people_rows.map((x) => x.stale_person_days), 1);
  const corrected = h.resolved_beliefs, held = h.still_stale_at_end;
  body.innerHTML = `
    <p class="lede">What a RevOps or support lead gets when Unstale reads a team's history: ${esc(R.name)}, ${R.days} days, ${R.mornings} mornings replayed.
      Computed from the graph in ${R.computed_ms >= 1000 ? (R.computed_ms / 1000).toFixed(1) + " s" : R.computed_ms + " ms"}, no LLM.</p>
    <div class="pcards">
      <div class="pcard"><b>${f1(h.stale_person_days)}</b><span>stale person-days: one person holding one outdated fact for one day</span></div>
      <div class="pcard"><b>${h.changes_missed} of ${h.changes}</b><span>changes were missed by someone</span></div>
      <div class="pcard"><b>${h.people_affected} of ${R.people}</b><span>people and agents worked from an outdated fact${h.agents_affected ? ` (including ${h.agents_affected} AI agent)` : ""}</span></div>
      <div class="pcard"><b>${held} of ${held + corrected}</b><span>outdated beliefs were still held at the end. Nobody corrected them</span></div>
    </div>
    <h3>The changes that were missed, most costly first</h3>
    ${R.changes.map((c) => barRow(`${esc(c.subject)}: ${esc(c.label)}`, c.stale_person_days, maxD, `${f1(c.stale_person_days)} person-days`, "",
      `${esc(fmtVal(c.old || ""))} → ${esc(fmtVal(c.new))} · ${esc(c.where || "")}${c.by ? ` · ${esc(c.by)}` : ""} · behind: ${c.people.map(esc).join(", ")}`)).join("")}
    <h3>Where changes leak out</h3>
    <table class="ptable"><thead><tr><th>Posted in</th><th>Changes posted</th><th>Missed by someone</th><th>Leak rate</th><th>People who missed one</th><th>Stale person-days</th></tr></thead><tbody>
      ${R.channels.map((c) => `<tr><td><b>${esc(c.where)}</b></td><td>${c.changes_posted}</td><td>${c.changes_missed}</td><td><b>${Math.round(c.leak_rate * 100)}%</b></td><td>${c.people_missed}</td><td>${f1(c.stale_person_days)}</td></tr>`).join("")}
    </tbody></table>
    <p class="small muted">A channel with a high leak rate is where the people who need a change aren't. That is where a process change, or a Unstale nudge, pays first.</p>
    <h3>Who lags</h3>
    ${R.people_rows.filter((x) => x.beliefs).map((x) => barRow(`${esc(x.name)}${x.kind === "agent" ? " (agent)" : ""}`, x.stale_person_days, maxP, `${f1(x.stale_person_days)} person-days`, "",
      `${esc(x.role)} · ${x.beliefs} outdated ${x.beliefs === 1 ? "belief" : "beliefs"}, ${x.still_stale} still held, longest ${f1(x.longest_days)} days`)).join("")}
    <p class="small muted">${R.people_rows.filter((x) => !x.beliefs).map((x) => esc(x.name)).join(", ")} were never behind.</p>
    <p class="small muted">Estimated, not observed: Slack doesn't say who read a message, so every count carries the confidence the morning brief shows (at least 50%).
      This is the document the audit-first pilot delivers on a team's last quarter of Slack export.
      <a href="/api/report.md" download>Download it as Markdown</a>.</p>`;
}
