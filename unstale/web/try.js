"use strict";
/* "Try it on the live graph": a person and a morning in, their belief diff out, computed live by the API.
   Uses $ and esc from landing.js. */
(() => {
  const WHO = [["person:maya", "Maya", "Account exec"], ["person:tom", "Tom", "Customer success"],
    ["agent:support-bot", "Support agent", "AI, answers customers"], ["person:lena", "Lena", "Pricing lead"]];
  const WHEN = [["2026-06-26T08:00:00Z", "Fri 26 Jun"], ["2026-06-29T08:00:00Z", "Mon 29 Jun"], ["2026-07-01T17:00:00Z", "Wed 1 Jul"]];
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = (ts) => { const x = new Date(ts); return `${DAYS[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`; };
  const val = (v) => (/^\d{4}-\d{2}-\d{2}$/.test(v || "") ? day(`${v}T12:00:00Z`) : (v ?? ""));
  const S = { who: "person:maya", when: "2026-06-29T08:00:00Z", seq: 0 };
  let meta = null;

  function chips(el, list, key) {
    el.innerHTML = list.map(([id, label, sub]) => `<button type="button" role="radio" class="chip" data-id="${esc(id)}" aria-checked="${S[key] === id}">
      <b>${esc(label)}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</button>`).join("");
    el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { S[key] = b.dataset.id; render(); });
  }
  const get = async (url, opt) => { const r = await fetch(url, opt); if (!r.ok) throw new Error(`${r.status}`); return r.json(); };

  function stats(parts) {
    $("try-stats").innerHTML = parts.map((p) => `<span>${p}</span>`).join("");
  }

  async function render() {
    chips($("try-who"), WHO, "who");
    chips($("try-when"), WHEN, "when");
    const seq = ++S.seq, who = WHO.find((w) => w[0] === S.who), when = WHEN.find((w) => w[0] === S.when);
    $("try-title").textContent = `${who[1]} · ${when[1]}`;
    $("try-badge").innerHTML = "";
    $("try-body").innerHTML = `<div class="try-empty">Asking the graph…</div>`;
    $("try-vs").hidden = true;
    const t0 = performance.now();
    let b;
    try { b = await get(`/api/brief/${encodeURIComponent(S.who)}?as_of=${encodeURIComponent(S.when)}&fresh=1`); }
    catch (e) { if (seq === S.seq) $("try-body").innerHTML = `<div class="try-empty">The demo is waking up (free instance). Try again in a moment.</div>`; return; }
    if (seq !== S.seq) return;
    const rtt = Math.round(performance.now() - t0);
    const n = b.items.length;
    $("try-badge").innerHTML = n ? `<i></i> behind on ${n}` : `<b class="ok-badge">up to date</b>`;
    $("try-body").innerHTML = n ? b.items.map((it, i) => `
      <div class="hh">@@ ${esc(it.subject)} · ${esc(it.label)} @@ <em>${Math.round(it.confidence * 100)}% sure</em></div>
      <div class="ln del"><span class="no"></span><span class="g">−</span><span class="t">${esc(val(it.believed))}</span><span class="note">${it.you_saw && it.you_saw.where ? `saw it · ${esc(it.you_saw.where)}` : "believes this"}</span></div>
      <div class="ln add"><span class="no"></span><span class="g">+</span><span class="t">${esc(val(it.current))}</span><span class="note">changed · ${esc(it.change.where || "")} · ${esc(it.change.author || "")}</span></div>
      ${it.why ? `<div class="why">${esc(it.why)}</div>` : ""}
      ${i === 0 ? `<button type="button" class="vs-btn" data-slot="${esc(it.slot)}">What would vector search say about this? →</button>` : ""}`).join("")
      : `<div class="try-empty">${esc(who[1])} isn't working from anything outdated on ${esc(when[1])}. Pick a later morning: changes land on Thu 25 and Fri 26 Jun.</div>`;
    stats([`${b.graph_queries} HydraDB ${b.graph_queries === 1 ? "query" : "queries"}`, `${b.ms} ms in the engine`, `${rtt} ms round trip`,
      `${b.llm_tokens} LLM tokens`, meta ? `store: ${esc(meta.store === "hydradb" ? "HydraDB 0.4.0 (open source)" : meta.store)}` : ""].filter(Boolean));
    const vb = $("try-body").querySelector(".vs-btn");
    if (vb) vb.onclick = () => vector(vb.dataset.slot, who[1]);
  }

  async function vector(slot, person) {
    const box = $("try-vs");
    box.hidden = false;
    box.innerHTML = `<p class="muted">Running the same question through a vector search…</p>`;
    let g;
    try { g = await get(`/api/graph?slot=${encodeURIComponent(slot)}&as_of=${encodeURIComponent(S.when)}`); }
    catch (e) { box.innerHTML = `<p class="muted">Couldn't load the comparison.</p>`; return; }
    const v = g.vector, stale = g.people.filter((p) => p.stale).map((p) => (p.kind === "agent" ? p.name : p.name.split(" ")[0]));
    const missing = new Set(g.missing.map((m) => m.person));
    box.innerHTML = `<div class="vs-mini">
      <div><p class="vs-title">Vector search${v ? ` for <i>"${esc(v.query)}"</i>` : ""}</p>
        ${v ? `<table>${v.results.slice(0, 3).map((r) => `<tr><td class="mono">${r.score.toFixed(2)}</td><td><b>${esc(r.author)}</b> ${esc(r.where)} <span class="muted">${esc(day(r.ts))}</span></td>
          <td>${r.states ? `<span class="vtag ${r.current ? "cur" : "old"}">${esc(val(r.states))} ${r.current ? "current" : "old"}</span>` : ""}</td></tr>`).join("")}</table>` : "<p class=\"muted\">No vector run recorded for this fact.</p>"}
        <p class="vs-foot">The right messages, old and new. Did ${esc(person)} read the new one? <b>Nothing in a search result can say.</b></p></div>
      <div class="dark"><p class="vs-title">The graph, same moment</p>
        <p class="big">${stale.length ? esc(stale.join(", ")) : "Nobody"}</p>
        <p class="vs-foot">${stale.length === 1 ? "is" : "are"} still on the old value. ${missing.size} ${missing.size === 1 ? "person has" : "people have"} no <code>SAW</code> edge to the message that changed it. One traversal, ${g.ms} ms, no model call.</p>
        <a class="btn line sm" href="/app">See the graph in the app →</a></div></div>`;
  }

  async function check() {
    const dr = meta && meta.drafts.find((d) => d.author === "person:maya");
    if (!dr) return;
    S.seq++;
    $("try-title").textContent = "Maya · Mon 29 Jun 08:55 · before sending";
    $("try-badge").innerHTML = "";
    $("try-vs").hidden = true;
    $("try-body").innerHTML = `<div class="draft">“${esc(dr.text)}”</div><div class="try-empty">Checking every fact in it against the record…</div>`;
    const t0 = performance.now();
    let r;
    try {
      r = await get("/api/check", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author: dr.author, text: dr.text, as_of: dr.as_of, channel: dr.channel }) });
    } catch (e) { $("try-body").innerHTML += `<div class="try-empty">Couldn't run the check.</div>`; return; }
    const readers = {};
    r.stale_readers.forEach((s) => { (readers[s.name] = readers[s.name] || []).push(`${s.subject_name} ${s.label}`); });
    $("try-badge").innerHTML = r.issues.length ? `<i></i> ${r.issues.length} outdated` : `<b class="ok-badge">all current</b>`;
    $("try-body").innerHTML = `<div class="draft">“${esc(dr.text)}”</div>` + r.issues.map((i) => `
      <div class="hh">@@ ${esc(i.subject_name)} · ${esc(i.label)} @@</div>
      <div class="ln del"><span class="no"></span><span class="g">−</span><span class="t">${esc(val(i.wrote_shown))}</span><span class="note">what the draft says</span></div>
      <div class="ln add"><span class="no"></span><span class="g">+</span><span class="t">${esc(val(i.current_shown))}</span><span class="note">changed · ${esc(i.change_where || "")} · ${esc(i.change_author || "")}</span></div>`).join("") +
      (Object.keys(readers).length ? `<div class="why">Also stale in #sales, so they'd believe it: ${Object.entries(readers).map(([n, f]) => `<b>${esc(n)}</b> (${esc(f.join(", "))})`).join("; ")}</div>` : "");
    stats([`${Math.round(performance.now() - t0)} ms round trip`, "draft facts extracted once and cached; the check itself is graph reads"]);
  }

  async function init() {
    try { meta = await get("/api/meta"); } catch (e) { /* render() shows the waking-up note */ }
    $("try-check").onclick = check;
    render();
  }
  init();
})();
