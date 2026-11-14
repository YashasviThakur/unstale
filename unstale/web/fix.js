"use strict";
/* "Fix it": who to tell about a changed fact, where, and a what-if of the corrections afterwards. Nothing is written. */

S.sim = [];
const simQS = () => (S.sim.length ? `&sim=${encodeURIComponent(JSON.stringify(S.sim))}` : "");

function planLine(st, F) {
  if (st.kind === "post") {
    const lows = st.mention.map((p) => F.stale.find((x) => x.person === p)).filter(Boolean);
    return `<li><b>Post in #${esc(st.channel)}</b> to reach ${st.reach_names.map(esc).join(", ")}.
      ${st.mention.length ? `<span class="muted">@mention ${st.mention_names.map(esc).join(", ")}: the graph thinks they read only about ${Math.round(Math.min(...st.mention.map((p) => st.rates[p])) * 100)}% of #${esc(st.channel)}, and a mention counts as seeing it.</span>`
        : `<span class="muted">Each of them reads about ${Math.round(Math.min(...Object.values(st.rates)) * 100)}% of #${esc(st.channel)} (the graph's estimate), so some chance remains.</span>`}</li>`;
  }
  if (st.kind === "agent") return `<li><b>Put the correction in ${esc(st.name)}'s context.</b> <span class="muted">No channel it reads reaches it; prepend the Unstale block to its prompt (MCP).</span></li>`;
  return `<li><b>Message ${esc(st.name)} directly.</b> <span class="muted">No channel you could post in reaches them.</span></li>`;
}

async function openFix(slot) {
  const F = await api(`/api/fix?${new URLSearchParams({ slot, as_of: S.asOf })}`);
  const active = S.sim.some((s) => s.slot === slot);
  const box = $("fix-body");
  const rem = F.expected_remaining;
  box.innerHTML = `
    <h3 class="slot-title">Close the gap: ${esc(F.title)}</h3>
    <p class="lede" style="margin-top:0">It is now <b>${esc(fmtVal(F.current))}</b>${F.changed_by ? ` (${esc(F.changed_by)} changed it in ${esc(F.changed_where || "a message")}, ${esc(fmtDay(F.changed_at))})` : ""}.
      ${F.stale.length ? `${F.stale.length} ${F.stale.length === 1 ? "person or agent is" : "people and agents are"} still on the old value.` : "Nobody who works on this is out of date."}</p>
    ${F.stale.length ? `
    <div class="fixgrid">
      <section>
        <div class="kicker">Still on the old value</div>
        <ul class="fixstale">${F.stale.map((x) => `<li><b>${esc(x.name)}</b> believes ${esc(fmtVal(x.believed))} <span class="conf ${x.confidence >= 0.9 ? "hi" : "mid"}">${Math.round(x.confidence * 100)}%</span></li>`).join("")}</ul>
        <div class="kicker" style="margin-top:14px">Plan, from the graph and the learned read rates</div>
        <ol class="fixplan">${F.plan.map((st) => planLine(st, F)).join("")}</ol>
      </section>
      <section>
        <div class="kicker">Draft message</div>
        <textarea id="fix-draft" rows="6" readonly>${esc(F.draft)}</textarea>
        <button type="button" class="btn ghost small" id="fix-copy">Copy</button>
        <div class="kicker" style="margin-top:14px">Predicted result</div>
        ${F.outcome.map((o) => `<div class="brow"><div class="bl">${esc(o.name)}</div><div class="bt"><i style="width:${Math.max(1, o.after * 100)}%"></i></div><div class="bv">${Math.round(o.before * 100)}% → ${Math.round(o.after * 100)}%</div></div>`).join("")}
        <p class="small muted" style="margin:6px 0 0">Chance each is still out of date after the plan, computed with the same function that makes the briefs, over their real exposures plus the ones this plan creates. About <b>${rem}</b> of ${F.stale.length} expected to remain.</p>
      </section>
    </div>
    <div class="fixactions">
      <button type="button" class="btn" id="fix-sim">${active ? "Simulated: corrections updated" : "Simulate sending this plan"}</button>
      <button type="button" class="btn ghost" id="fix-close">Close</button>
      <span class="small muted">A what-if: nothing is written to the graph, so it is safe on the public demo. Run locally with Send to write it.</span>
    </div>` : `<p class="muted">Nothing to fix.</p>`}`;
  openDlg($("fix-dialog"));
  if (!F.stale.length) return;
  $("fix-copy").onclick = () => { navigator.clipboard?.writeText(F.draft); $("fix-copy").textContent = "Copied"; };
  $("fix-close").onclick = () => $("fix-dialog").close();
  $("fix-sim").onclick = async () => {
    S.sim = S.sim.filter((s) => s.slot !== slot).concat(F.effects);
    S.simTitle = F.title;
    $("fix-dialog").close();
    await refresh();
  };
}

function renderSimBanner() {
  const el = $("sim-banner");
  if (!S.sim.length) { el.classList.add("hidden"); return; }
  const slots = [...new Set(S.sim.map((s) => s.slot))];
  el.classList.remove("hidden");
  el.innerHTML = `<b>Simulating</b> ${slots.length === 1 ? `the plan for ${esc(S.simTitle || slots[0])}` : `${slots.length} plans`} as sent at ${esc(fmtTs(S.sim[0].ts))}. Corrections below show what would be left.
    <button type="button" class="linkish" id="sim-reset">Reset</button>`;
  $("sim-reset").onclick = async () => { S.sim = []; await refresh(); };
}
