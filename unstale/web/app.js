"use strict";

const S = { meta: null, viewer: "person:maya", asOf: null, channel: null, tab: "feed", steps: [], team: null };
const $ = (id) => document.getElementById(id);
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function d(ts) { return new Date(ts); }
function fmtDay(ts) { const x = d(ts); return `${DAYS[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`; }
function fmtTime(ts) { const x = d(ts); return `${String(x.getUTCHours()).padStart(2, "0")}:${String(x.getUTCMinutes()).padStart(2, "0")}`; }
function fmtTs(ts) { return `${fmtDay(ts)}, ${fmtTime(ts)} UTC`; }
function fmtVal(v) {
  if (v == null) return "";
  let m = /^(\d{4}-\d{2}-\d{2})$/.exec(v);
  if (m) return fmtDay(`${m[1]}T12:00:00Z`);
  m = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC$/.exec(v);
  if (m) return `${fmtDay(`${m[1]}T12:00:00Z`)}, ${m[2]} UTC`;
  return v;
}
function initials(name) { return name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase(); }
function person(id) { return S.meta.people.find((p) => p.id === id); }
function firstName(id) { const p = person(id); return p ? p.name.split(" ")[0] : id; }

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* keep status text */ }
    throw new Error(msg);
  }
  return r.json();
}

/* ---------------- time ---------------- */
function buildSteps() {
  const start = d(S.meta.start).getTime();
  const end = d(S.meta.end).getTime();
  S.steps = [];
  for (let t = start; t <= end; t += 30 * 60 * 1000) S.steps.push(new Date(t).toISOString().replace(".000", ""));
  if (S.steps[S.steps.length - 1] !== S.meta.end) S.steps.push(S.meta.end);
  const scrub = $("scrub");
  scrub.max = S.steps.length - 1;
  scrub.oninput = () => { S.asOf = S.steps[+scrub.value]; renderClock(); };
  scrub.onchange = () => refresh();
  $("ticks").innerHTML = S.meta.checkpoints.map((cp, i) => {
    const lab = i === S.meta.checkpoints.length - 1 ? "End" : fmtDay(cp).split(" ").slice(0, 2).join(" ");
    return `<button data-ts="${cp}">${lab}</button>`;
  }).join("");
  $("ticks").querySelectorAll("button").forEach((b) => b.onclick = () => setTime(b.dataset.ts));
}
function setTime(ts) {
  S.asOf = ts;
  const t = d(ts).getTime();
  let best = 0;
  S.steps.forEach((s, i) => { if (d(s).getTime() <= t) best = i; });
  $("scrub").value = best;
  renderClock();
  refresh();
}
function renderClock() {
  $("clock-label").textContent = fmtTs(S.asOf);
  $("ticks").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.ts === S.asOf));
  const atEnd = d(S.asOf).getTime() >= d(S.meta.last_ts).getTime();
  $("btn-send").disabled = !atEnd;
}

/* ---------------- viewers & channels ---------------- */
function renderViewers() {
  const counts = {};
  (S.team?.people || []).forEach((r) => { counts[r.person] = r.stale.length; });
  $("viewer-list").innerHTML = S.meta.people.map((p) => `
    <button class="viewer ${p.kind === "agent" ? "agent" : ""} ${p.id === S.viewer ? "on" : ""}" data-id="${p.id}" title="${esc(p.role)}">
      <span class="initials">${p.kind === "agent" ? "AI" : initials(p.name)}</span>
      <span>${esc(p.kind === "agent" ? p.name : p.name.split(" ")[0])}</span>
      <span class="count">${counts[p.id] ? counts[p.id] : ""}</span>
    </button>`).join("");
  $("viewer-list").querySelectorAll(".viewer").forEach((b) => b.onclick = () => {
    S.viewer = b.dataset.id; S.channel = null; S.draftTo = null; S.draftToIds = null;
    $("check-result").innerHTML = ""; renderViewers(); renderChannels(); renderComposeTarget(); refresh();
  });
}
function renderChannels() {
  const mine = Object.entries(S.meta.channels).filter(([, members]) => members.includes(S.viewer)).map(([c]) => c);
  const items = [["", "Everything"], ...mine.map((c) => [c, `#${c}`]), ["inbox", "Email and DMs"]];
  $("channel-list").innerHTML = items.map(([id, lab]) =>
    `<li><button data-ch="${id}" class="${(S.channel || "") === id ? "on" : ""}">${esc(lab)}</button></li>`).join("");
  $("channel-list").querySelectorAll("button").forEach((b) => b.onclick = () => {
    S.channel = b.dataset.ch || null; renderChannels(); loadFeed(); renderComposeTarget();
  });
}

/* ---------------- feed ---------------- */
async function loadFeed() {
  const q = new URLSearchParams({ viewer: S.viewer, as_of: S.asOf });
  if (S.channel) q.set("channel", S.channel);
  const { messages } = await api(`/api/feed?${q}`);
  if (!messages.length) { $("feed").innerHTML = `<p class="empty">Nothing here yet at this time.</p>`; return; }
  let html = "", day = "";
  for (const m of messages) {
    const md = fmtDay(m.ts);
    if (md !== day) { day = md; html += `<div class="day">${md}</div>`; }
    const echo = m.claims.some((c) => c.kind === "echo");
    const claims = m.claims.map((c) => `
      <span class="claim ${c.outdated ? "outdated" : ""} ${c.kind === "echo" ? "echo" : ""}" data-slot="${esc(c.slot)}"
        title="${c.outdated ? `Out of date. Now: ${esc(fmtVal(c.now))}` : "Current"}${c.kind === "echo" ? ". Repeated an older value." : ""}">
        ${esc(c.label)}: <span class="v">${esc(fmtVal(c.value))}</span></span>`).join("");
    const where = m.kind === "slack" ? m.where : `${m.where}${m.to.length ? ` to ${m.to.join(", ")}` : ""}`;
    html += `
      <article class="msg">
        <div class="ts">${fmtTime(m.ts)}</div>
        <div>
          <span class="who">${esc(m.author_name)}</span><span class="where">${esc(where)}</span>
          ${m.thread ? `<span class="thread">in thread</span>` : ""}
          ${m.subject_line ? `<div class="small muted">${esc(m.subject_line)}</div>` : ""}
          <div class="body">${esc(m.text)}</div>
          ${m.reactions.length ? `<div class="meta">Reacted: ${esc(m.reactions.join(", "))}</div>` : ""}
          ${claims ? `<div class="claims">${claims}</div>` : ""}
          ${echo ? `<div class="note-echo">This message repeated a fact that had already changed.</div>` : ""}
        </div>
      </article>`;
  }
  $("feed").innerHTML = html;
  $("feed").querySelectorAll(".claim").forEach((el) => el.onclick = () => openSlot(el.dataset.slot));
  requestAnimationFrame(() => { $("feed").scrollTop = $("feed").scrollHeight; });
}

/* ---------------- corrections ---------------- */
async function loadBrief() {
  const p = person(S.viewer);
  const b = await api(`/api/brief/${encodeURIComponent(S.viewer)}?as_of=${encodeURIComponent(S.asOf)}`);
  const n = b.items.length;
  const who = p.kind === "agent" ? "this agent" : p.name.split(" ")[0];
  $("corr-kicker").textContent = p.kind === "agent" ? "Corrections for an agent" : "Corrections";
  $("corr-title").textContent = n
    ? `${n} thing${n > 1 ? "s" : ""} ${who} believe${p.kind === "agent" || n ? "s" : ""} that ${n > 1 ? "are" : "is"} no longer true`
    : `${who === "this agent" ? "This agent is" : `${who} is`} up to date`;
  $("corr-meta").textContent = `${b.graph_queries} graph reads, ${b.ms} ms, ${b.llm_tokens} LLM tokens.`;
  if (!n) {
    $("corr-list").innerHTML = `<div class="clean">Nothing ${who === "this agent" ? "it has" : "they have"} seen about their work has changed since.</div>`;
  } else {
    $("corr-list").innerHTML = b.items.map((it) => `
      <div class="card">
        <div class="topic">${esc(it.subject)} <span class="lab">${esc(it.label)}</span>
          <span class="hop">${it.hops === 0 ? "yours" : "linked to your work"}</span>
          <span class="conf ${it.confidence >= 0.9 ? "hi" : it.confidence >= 0.7 ? "mid" : "lo"}" title="Chance this is still what they believe">${Math.round(it.confidence * 100)}%</span></div>
        <div class="vals">
          <span class="k">You think</span><span class="old">${esc(fmtVal(it.believed))}</span>
          <span class="k">Now</span><span class="new">${esc(fmtVal(it.current))}</span>
        </div>
        <div class="trail">
          <div>You saw it: ${esc(it.you_saw.author)}, ${esc(it.you_saw.where)}, ${esc(fmtDay(it.you_saw.ts))}. <q>${esc(it.you_saw.text)}</q></div>
          <div>Changed: ${esc(it.change.author)}, ${esc(it.change.where)}, ${esc(fmtDay(it.change.ts))}. <q>${esc(it.change.text)}</q></div>
          <div class="why">${esc(it.why || "")}${it.echo ? ` ${esc(it.echo)}, which is where you picked up the old value.` : ""}</div>
          ${it.believed_via.strength === "weak" ? `<div class="via">Assumed seen: you're in #${esc(it.believed_via.channel)}, and the graph thinks you read about ${Math.round(it.believed_via.read_rate * 100)}% of it.</div>` : ""}
        </div>
        <div class="acts">
          ${p.kind === "agent" ? "" : `<span class="fb" data-slot="${esc(it.slot)}">
            <button class="btn small" data-v="news">News to me</button>
            <button class="btn small ghost" data-v="knew">I knew this</button>
            <button class="btn small ghost" data-v="neither">Never heard of it</button></span>`}
          <button class="linkish" data-open="${esc(it.slot)}">Who else believes what</button>
          <div class="fb-note small muted"></div>
        </div>
      </div>`).join("");
    $("corr-list").querySelectorAll("[data-open]").forEach((el) => el.onclick = () => openSlot(el.dataset.open));
    $("corr-list").querySelectorAll(".fb button").forEach((el) => el.onclick = () => sendFeedback(el));
  }
  if (p.kind === "agent") {
    const c = await api(`/api/agent/${encodeURIComponent(S.viewer)}/context?as_of=${encodeURIComponent(S.asOf)}`);
    $("agent-context").textContent = c.context;
    $("agent-block").classList.remove("hidden");
  } else {
    $("agent-block").classList.add("hidden");
  }
}

async function sendFeedback(btn) {
  const wrap = btn.closest(".fb");
  const note = btn.closest(".acts").querySelector(".fb-note");
  wrap.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    const r = await api("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ person: S.viewer, slot: wrap.dataset.slot, verdict: btn.dataset.v, as_of: S.asOf }) });
    const learnt = r.rates.map((x) => `#${x.channel} now ${Math.round(x.rate * 100)}%`).join(", ");
    note.textContent = r.evidence
      ? `Written to the graph: ${r.evidence} read signal${r.evidence > 1 ? "s" : ""}. ${firstName(S.viewer)}'s read rate: ${learnt}.`
      : "Thanks. Nothing new to learn here: the change was in a channel they aren't in.";
    setTimeout(() => refresh(), 900);
  } catch (e) {
    note.textContent = `Couldn't save: ${e.message}`;
    wrap.querySelectorAll("button").forEach((b) => { b.disabled = false; });
  }
}

/* ---------------- team ---------------- */
async function loadTeam() {
  S.team = await api(`/api/team?as_of=${encodeURIComponent(S.asOf)}`);
  renderViewers();
  const total = S.team.people.reduce((a, r) => a + r.stale.length, 0);
  $("team").innerHTML = `
    <p class="muted" style="margin:14px 0 0">${total} outdated beliefs across the team at ${esc(fmtTs(S.asOf))}.</p>
    <table class="team-table">
      <thead><tr><th></th><th>Person</th><th>Working from an old version of</th></tr></thead>
      <tbody>${S.team.people.map((r) => `
        <tr>
          <td class="n ${r.stale.length ? "" : "zero"}">${r.stale.length}</td>
          <td><strong>${esc(r.name)}</strong><div class="small muted">${esc(r.role)}</div></td>
          <td>${r.stale.length ? r.stale.map((s) => `<span class="chip" data-slot="${esc(s.slot)}">${esc(s.subject)} ${esc(s.label)}: <s>${esc(fmtVal(s.believed))}</s> now ${esc(fmtVal(s.current))}</span>`).join("") : `<span class="small muted">In sync</span>`}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
  $("team").querySelectorAll("[data-slot]").forEach((el) => el.onclick = () => openSlot(el.dataset.slot));
  const L = await api(`/api/learned?as_of=${encodeURIComponent(S.asOf)}`);
  const src = Object.entries(L.by_source).map(([k, v]) => `${v} from ${k === "feedback" ? "feedback" : k + "es"}`).join(", ");
  $("team").insertAdjacentHTML("beforeend", `
    <div class="learned">
      <div class="kicker">What the graph has learned about reading</div>
      <p class="small muted">${L.evidence ? `${L.evidence} read signal${L.evidence === 1 ? "" : "s"} so far (${esc(src)}). Org-wide read rate ${Math.round(L.org_rate * 100)}%.` :
        "No read signals yet. Every channel member is assumed to read 80% of their channel until feedback, echoes or restatements say otherwise."}</p>
      ${L.pairs.length ? `<table class="team-table"><thead><tr><th>Person</th><th>Channel</th><th>Read</th><th>Missed</th><th>Estimated read rate</th></tr></thead><tbody>
        ${L.pairs.map((r) => `<tr><td>${esc(r.name)}</td><td>#${esc(r.channel)}</td><td>${r.read.toFixed(1)}</td><td>${r.missed.toFixed(1)}</td>
          <td><span class="bar"><span style="width:${Math.round(r.rate * 100)}%"></span></span> ${Math.round(r.rate * 100)}%</td></tr>`).join("")}
      </tbody></table>` : ""}
    </div>`);
}

/* ---------------- slot dialog ---------------- */
async function openSlot(slot) {
  const [subject, attribute] = slot.split("|");
  const v = await api(`/api/slot?${new URLSearchParams({ subject, attribute, as_of: S.asOf })}`);
  const cur = v.current ? v.current.value : null;
  const groups = {};
  for (const [pid, b] of Object.entries(v.people)) {
    const key = b.believes == null ? "_none" : b.shown;
    (groups[key] ||= []).push({ pid, ...b });
  }
  const groupHtml = Object.entries(groups).map(([k, list]) => {
    if (k === "_none") return `<div class="group"><div class="k">Never saw anything about it</div><div class="names">${list.map((x) => esc(x.name)).join(", ")}</div></div>`;
    const isCur = list[0].believes != null && cur != null && list[0].believes.toLowerCase() === cur.toLowerCase();
    return `<div class="group ${isCur ? "sync" : "stale"}"><div class="k">${isCur ? "Believes the current value" : "Still believes"}: ${esc(fmtVal(k))}</div>
      <div class="names">${list.map((x) => `${esc(x.name)}${x.relevant ? "" : " (not their area)"}`).join(", ")}</div></div>`;
  }).join("");
  $("slot-body").innerHTML = `
    <h3 class="slot-title">${esc(v.title)}</h3>
    <div class="kicker" style="margin-bottom:8px">Versions, from the graph's history</div>
    <ul class="versions">${v.versions.map((x) => `
      <li class="${cur != null && x.value === cur && !x.until ? "now" : ""}">
        <div class="v">${esc(fmtVal(x.shown))}</div>
        <div class="src">${esc(fmtTs(x.since))}, ${esc(x.author || "")} in ${esc(x.where || "")}${x.until ? `. Replaced ${esc(fmtDay(x.until))}.` : ". Current."}</div>
      </li>`).join("")}</ul>
    <div class="kicker" style="margin-bottom:8px">Who believes what</div>
    <div class="groups">${groupHtml}</div>`;
  $("slot-dialog").showModal();
}

/* ---------------- compose ---------------- */
function renderComposeTarget() {
  const p = person(S.viewer);
  $("compose-label").textContent = p.kind === "agent" ? "Agent's draft answer" : `Draft as ${p.name.split(" ")[0]}`;
  $("compose-target").textContent = S.channel && S.channel !== "inbox" ? `To #${S.channel}` : (S.draftTo ? `To ${S.draftTo}` : "No channel picked: checks facts only");
  const presets = S.meta.drafts.map((dr, i) => `<button type="button" class="preset" data-i="${i}">Try: ${esc(firstName(dr.author))}'s ${dr.kind === "agent" ? "answer" : dr.kind}</button>`).join("");
  $("draft-presets").innerHTML = presets;
  $("draft-presets").querySelectorAll(".preset").forEach((b) => b.onclick = () => {
    const dr = S.meta.drafts[+b.dataset.i];
    S.viewer = dr.author; S.channel = dr.channel || null; S.draftTo = dr.to ? dr.to.join(", ") : null;
    S.draftToIds = dr.to || [];
    $("draft").value = dr.text;
    $("check-result").innerHTML = "";
    renderViewers();
    renderChannels();
    renderComposeTarget();
    setTime(dr.as_of);
  });
}
async function runCheck() {
  const text = $("draft").value.trim();
  if (!text) return;
  $("check-result").innerHTML = `<div class="verdict">Checking against the record...</div>`;
  const body = { author: S.viewer, text, as_of: S.asOf };
  if (S.channel && S.channel !== "inbox") body.channel = S.channel; else if (S.draftToIds) body.to = S.draftToIds;
  try {
    const r = await api("/api/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const parts = [];
    for (const i of r.issues) {
      parts.push(`<div class="verdict bad"><strong>${i.kind === "outdated" ? "Out of date" : "Conflicts with the record"}: ${esc(i.subject_name)} ${esc(i.label)} is ${esc(fmtVal(i.current_shown))}, not ${esc(fmtVal(i.wrote_shown))}.</strong>
        Changed ${esc(fmtDay(i.changed_at))} by ${esc(i.change_author || "someone")} in ${esc(i.change_where || "a message")}.
        ${i.kind === "outdated" ? "You never saw that change." : "If you mean to change it, say so explicitly."}</div>`);
    }
    const readers = {};
    for (const s of r.stale_readers) (readers[s.name] ||= []).push(s);
    for (const [who, list] of Object.entries(readers)) {
      const what = list.map((s) => `${esc(s.subject_name)} ${esc(s.label)} is ${esc(fmtVal(s.believes_shown))} (now ${esc(fmtVal(s.current_shown))})`).join("; ");
      parts.push(`<div class="verdict warn"><strong>${esc(who)} will read this and still thinks ${what}.</strong>${r.issues.length ? "" : " Worth saying so."}</div>`);
    }
    if (!parts.length) parts.push(`<div class="verdict ok"><strong>Nothing in this draft contradicts the current record.</strong> ${r.claims.length} fact${r.claims.length === 1 ? "" : "s"} checked.</div>`);
    parts.push(`<div class="small muted">${r.claims.length} facts read from the draft, ${r.llm_tokens} LLM tokens.</div>`);
    $("check-result").innerHTML = parts.join("");
  } catch (e) {
    $("check-result").innerHTML = `<div class="verdict warn">Check failed: ${esc(e.message)}</div>`;
  }
}
async function runSend() {
  const text = $("draft").value.trim();
  if (!text) return;
  const body = { author: S.viewer, text, as_of: S.asOf };
  if (S.channel && S.channel !== "inbox") body.channel = S.channel; else if (S.draftToIds) body.to = S.draftToIds;
  try {
    await api("/api/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("draft").value = "";
    $("check-result").innerHTML = `<div class="verdict ok"><strong>Sent and written to the graph.</strong> Corrections below are recomputed.</div>`;
    refresh();
  } catch (e) {
    $("check-result").innerHTML = `<div class="verdict warn">Send failed: ${esc(e.message)}</div>`;
  }
}

/* ---------------- wiring ---------------- */
async function refresh() {
  renderClock();
  const jobs = [loadBrief(), loadTeam()];
  if (S.tab === "feed") jobs.push(loadFeed());
  await Promise.all(jobs).catch((e) => console.error(e));
}

document.querySelectorAll(".tab").forEach((t) => t.onclick = () => {
  S.tab = t.dataset.tab;
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $("feed").classList.toggle("hidden", S.tab !== "feed");
  $("team").classList.toggle("hidden", S.tab !== "team");
  if (S.tab === "feed") loadFeed();
});
$("btn-check").onclick = runCheck;
$("btn-send").onclick = runSend;
$("btn-copy").onclick = () => navigator.clipboard?.writeText($("agent-context").textContent);

(async function init() {
  S.meta = await api("/api/meta");
  $("orgname").textContent = `Demo team: ${S.meta.name}.`;
  $("graph-note").textContent = (S.meta.store === "hydradb" ? `HydraDB namespace ${S.meta.namespace}.` : `Hosted demo on SelfGraph's embedded Kuzu store (the full build runs on HydraDB; see the repo).`) + " Facts are versioned by SelfGraph; beliefs are traversals over who saw which message.";
  buildSteps();
  renderViewers();
  renderChannels();
  renderComposeTarget();
  setTime("2026-06-29T08:00:00Z");
})();
