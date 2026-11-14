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
  const lo = Math.floor(Math.min(...pts.map((p) => p.false_alarms_ci[0])) / 5) * 5;
  const hi = Math.ceil(Math.max(...pts.map((p) => p.false_alarms_ci[1])) / 5) * 5;
  const x = (n) => L + (n / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const band = pts.map((p, i) => `${x(i)},${y(p.false_alarms_ci[1])}`).join(" ") + " " +
    [...pts].reverse().map((p, i) => `${x(pts.length - 1 - i)},${y(p.false_alarms_ci[0])}`).join(" ");
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.false_alarms_per_100_briefs)}`).join(" ");
  const grid = [];
  for (let v = lo; v <= hi; v += 5) grid.push(`<line class="cg" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ct" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`);
  const base = pts[0].false_alarms_per_100_briefs;
  return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="False alarms per 100 briefs by prior sprints of evidence">
    ${grid.join("")}
    <polygon class="cband" points="${band}"/>
    <line class="cbase" x1="${L}" x2="${W - R}" y1="${y(base)}" y2="${y(base)}"/>
    <text class="ct" x="${W - R}" y="${y(base) - 6}" text-anchor="end">baseline: no prior evidence</text>
    <path class="cline" d="${line}"/>
    ${pts.map((p, i) => `<circle class="cdot" cx="${x(i)}" cy="${y(p.false_alarms_per_100_briefs)}" r="4"/>
      <text class="cval" x="${x(i)}" y="${y(p.false_alarms_per_100_briefs) - 10}" text-anchor="middle">${p.false_alarms_per_100_briefs}</text>
      <text class="ct" x="${x(i)}" y="${H - 30}" text-anchor="middle">${i}</text>`).join("")}
    <text class="ct" x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle">earlier sprints of evidence the graph has learned from</text>
    <text class="ct" transform="translate(13 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">false alarms per 100 briefs (lower is better)</text></svg>`;
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

      <h3>3. It gets sharper every run</h3>
      <p class="small muted">${cv.orgs} further orgs the engine had never seen (seeds 101-140, five sprints each). The same final sprint is scored again with evidence from only the first <i>n</i> sprints: people's "news to me / I knew this" answers, plus echoes and restatements.</p>
      ${curveSvg(cv)}
      <div class="pcards three">
        <div class="pcard"><b>${f1(d.false_alarms_per_100_briefs.mean)} <small>[${d.false_alarms_per_100_briefs.ci95.map(f1).join(", ")}]</small></b><span>change in false alarms per 100 briefs, ${last.prior_sprints} sprints vs none (95% interval over orgs)</span></div>
        <div class="pcard"><b>${d.false_alarms_per_100_briefs.orgs_improved} of ${cv.orgs}</b><span>orgs got fewer false alarms. Precision ${f2(first.precision)} → ${f2(last.precision)}, F1 ${f2(first.f1)} → ${f2(last.f1)} (+${d.f1.mean.toFixed(3)} [${d.f1.ci95.map((x) => x.toFixed(3)).join(", ")}])</span></div>
        <div class="pcard"><b>${B.same_sprint_after_n_prior_sprints.map((x) => f1(x.false_alarms_per_100_briefs)).join(" → ")}</b><span>the same effect in the 20-org benchmark above, with 0, 1, 2 prior sprints</span></div>
      </div>
      <p class="small muted">Baseline is the same engine with no prior evidence. F1 moves less than precision: learning removes false alarms, while recall is capped by beliefs nothing observable reveals. Reproduce: <code>python scripts/bench.py --curve --orgs 40 --first 101 --sprints 5</code>.</p>

      <h3>4. Agents</h3>
      <p class="small muted">A support agent reads its own knowledge-base channel; prices, refund windows and API status change elsewhere. A customer asks about each fact it is responsible for (${ag.own.questions} questions, 4 generated orgs and Northwind).</p>
      ${agRows.map(([k, n]) => barRow(esc(n), ag[k].accuracy, 1, `${pct(ag[k].accuracy)} correct`, k === "unstale" ? "us" : "", `${ag[k].prompt_tokens_per_answer.toLocaleString()} prompt tokens · ${ag[k].outdated_answers} outdated answers`)).join("")}
      <p class="small muted">Vector RAG does well here because it was allowed to search every channel in the company. That is a permissions decision most teams will not make for a customer-facing bot. With the access it already has, the agent is right ${pct(ag.own.accuracy)} of the time and confidently outdated ${ag.own.outdated_answers} times; Unstale's block fixes that with no new access. Reproduce: <code>python scripts/agent_eval.py</code>.</p>

      <h3>5. Calibration</h3>
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

function openPitch() {
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
          <ol><li><b>Check before sending</b> for customer-facing people.</li><li><b>Morning corrections</b> with a "news to me" button that teaches the graph.</li><li><b>A correction block for agents</b> over MCP, about 100 extra tokens per answer.</li></ol>
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
      <div class="cta"><b>Next 90 days:</b> Slack app (morning DM, message-action check) → three design partners running a four-week pilot measured in <i>outdated statements caught before they reached a customer</i> → publish the benchmark as an open dataset.
        <a class="btn" href="https://github.com/YashasviThakur/unstale/issues/new?title=Design%20partner%3A%20&body=Team%20size%3A%0AWhere%20decisions%20are%20made%20(Slack%2FTeams%2Femail)%3A%0AWhat%20goes%20stale%20for%20you%3A" target="_blank" rel="noopener">Be a design partner</a>
        <a class="btn ghost" href="https://github.com/YashasviThakur/unstale" target="_blank" rel="noopener">Repo</a></div>`;
  }
  openDlg($("pitch-dialog"));
}
