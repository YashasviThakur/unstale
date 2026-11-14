"use strict";
/* The graph behind one fact: people -SAW-> messages -ASSERTS-> fact versions, plus the edge that is missing. */

const SVGNS = "http://www.w3.org/2000/svg";

function graphSvg(g, focus) {
  const W = 940, PX = 0, PW = 168, MX = 318, MW = 300, VX = 740, VW = 200;
  const rowP = 46, rowM = 62;
  const people = [...g.people].sort((a, b) => (b.stale - a.stale) || (b.relevant - a.relevant) || a.name.localeCompare(b.name));
  const msgs = g.messages;
  const H = Math.max(people.length * rowP, msgs.length * rowM, 240) + 56;
  const pY = (i) => 34 + i * rowP + (H - 56 - people.length * rowP) / 2 + 18;
  const mY = (i) => 34 + i * rowM + (H - 56 - msgs.length * rowM) / 2 + 26;
  const pos = { p: {}, m: {}, v: {} };
  people.forEach((p, i) => { pos.p[p.id] = pY(i); });
  msgs.forEach((m, i) => { pos.m[m.id] = mY(i); });
  // Versions sit beside the messages that assert them.
  g.versions.forEach((v, i) => {
    const ys = g.asserts.filter((a) => a.version === v.id).map((a) => pos.m[a.message]).filter((y) => y != null);
    pos.v[v.id] = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 60 + i * 90;
  });
  // Keep versions from overlapping.
  const order = g.versions.map((v) => v.id).sort((a, b) => pos.v[a] - pos.v[b]);
  order.forEach((id, i) => { if (i && pos.v[id] - pos.v[order[i - 1]] < 70) pos.v[id] = pos.v[order[i - 1]] + 70; });

  const curve = (x1, y1, x2, y2) => `M${x1},${y1} C${x1 + (x2 - x1) * 0.55},${y1} ${x2 - (x2 - x1) * 0.55},${y2} ${x2},${y2}`;
  const f = (id) => (focus && id !== focus ? " dim" : (focus ? " hot" : ""));
  const parts = [];
  parts.push(`<text class="gcol" x="${PX}" y="14">PEOPLE AND AGENTS</text><text class="gcol" x="${MX}" y="14">MESSAGES THAT STATE IT</text><text class="gcol" x="${VX}" y="14">VERSIONS OF THE FACT (SelfGraph)</text>`);

  // fact version chain
  for (let i = 0; i + 1 < g.versions.length; i++) {
    const a = g.versions[i], b = g.versions[i + 1];
    const y1 = pos.v[a.id] + 22, y2 = pos.v[b.id] - 22;
    parts.push(`<path class="e sup" d="M${VX + 40},${y1} L${VX + 40},${y2}" marker-end="url(#arrow-dark)"/><text class="elab" x="${VX + 48}" y="${(y1 + y2) / 2 + 3}">superseded by</text>`);
  }
  // message -> version
  for (const a of g.asserts) {
    const v = g.versions.find((x) => x.id === a.version);
    const cls = v && v.current ? "ok" : "old";
    parts.push(`<path class="e asserts ${cls}" d="${curve(MX + MW, pos.m[a.message], VX, pos.v[a.version])}" marker-end="url(#arrow-${cls})"><title>${esc(a.kind)}: this message states that value</title></path>`);
  }
  // person -> message (saw)
  for (const s of g.saw) {
    const y1 = pos.p[s.person], y2 = pos.m[s.message];
    if (y1 == null || y2 == null) continue;
    const tip = s.strength === "strong" ? "Saw it: posted, replied, reacted, was mentioned or emailed" :
      `Assumed: member of #${s.channel}. The graph estimates ${Math.round(s.rate * 100)}% of that channel gets read`;
    parts.push(`<path class="e saw ${s.strength}${f(s.person)}" data-p="${esc(s.person)}" d="${curve(PX + PW, y1, MX, y2)}"><title>${esc(tip)}</title></path>`);
  }
  // missing edges
  for (const x of g.missing) {
    const y1 = pos.p[x.person], y2 = pos.m[x.message];
    if (y1 == null || y2 == null) continue;
    const p = g.people.find((q) => q.id === x.person);
    parts.push(`<path class="e missing${f(x.person)}" data-p="${esc(x.person)}" d="${curve(PX + PW, y1, MX, y2)}"><title>${esc(p ? p.name : "")} has no SAW edge to the message that changed this</title></path>`);
    if (focus === x.person) {
      const mx = MX - 64, my = y1 + (y2 - y1) * 0.78;
      parts.push(`<g class="xmark"><circle cx="${mx}" cy="${my}" r="9"/><path d="M${mx - 4},${my - 4} L${mx + 4},${my + 4} M${mx + 4},${my - 4} L${mx - 4},${my + 4}"/></g><text class="xlab" x="${mx}" y="${my + 24}" text-anchor="middle">no SAW edge</text>`);
    }
  }
  // nodes
  people.forEach((p) => {
    const y = pos.p[p.id];
    const cls = p.stale ? "stale" : p.in_sync ? "sync" : "none";
    parts.push(`<g class="node person ${cls}${focus && p.id === focus ? " focus" : ""}" data-p="${esc(p.id)}" tabindex="0" role="button" aria-label="Show ${esc(p.name)}'s path">
      <rect x="${PX}" y="${y - 19}" width="${PW}" height="38" rx="8"/>
      <text class="n1" x="${PX + 10}" y="${y - 3}">${esc(p.kind === "agent" ? p.name : p.name)}</text>
      <text class="n2" x="${PX + 10}" y="${y + 11}">${p.believes ? "thinks " + esc(fmtVal(p.believes)) : "never saw it"}</text></g>`);
  });
  msgs.forEach((m) => {
    const y = pos.m[m.id], isNow = g.versions.some((v) => v.message === m.id && v.current);
    parts.push(`<g class="node msg ${m.kind}${isNow ? " now" : ""}"><title>${esc(m.author)} ${esc(m.where)}: ${esc(m.text)}</title>
      <rect x="${MX}" y="${y - 24}" width="${MW}" height="48" rx="8"/>
      <text class="n1" x="${MX + 10}" y="${y - 7}">${esc(m.author)}, ${esc(m.where)}</text>
      <text class="n2" x="${MX + 10}" y="${y + 8}">${esc(fmtDay(m.ts))} · ${m.kind === "update" ? "states" : m.kind === "echo" ? "repeats an old value" : "restates"} ${esc(fmtVal(m.value))}</text>
      <text class="n3" x="${MX + 10}" y="${y + 20}">${esc(m.id)}${isNow ? " · the change" : ""}</text></g>`);
  });
  g.versions.forEach((v, i) => {
    const y = pos.v[v.id];
    parts.push(`<g class="node ver ${v.current ? "cur" : "old"}">
      <rect x="${VX}" y="${y - 22}" width="${VW}" height="44" rx="8"/>
      <text class="n1" x="${VX + 10}" y="${y - 4}">${esc(fmtVal(v.shown))}</text>
      <text class="n2" x="${VX + 10}" y="${y + 12}">v${i + 1} · ${v.current ? "current" : "replaced " + esc(fmtDay(v.until || v.since))}</text></g>`);
  });
  const defs = `<defs>
    <marker id="arrow-ok" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#0f8a5f"/></marker>
    <marker id="arrow-old" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#cc3b4b"/></marker>
    <marker id="arrow-dark" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#0b2545"/></marker></defs>`;
  return `<svg class="fgraph" viewBox="0 0 ${W} ${H}" role="img" aria-label="Graph of who saw which version of ${esc(g.title)}">${defs}${parts.join("")}</svg>`;
}

function vectorBlock(g, who) {
  const v = g.vector;
  if (!v || !v.results.length) return `<div class="gvs"><strong>On a vector store</strong> a search returns the messages about this topic and nothing about who read which. Measured on our labelled team: F1 0.13.</div>`;
  const seenBy = (mid) => (who ? g.saw.find((x) => x.person === who.id && x.message === mid) : null);
  const rows = v.results.map((r) => {
    const saw = seenBy(r.message);
    const last = !who ? "" : r.states == null ? `<span class="muted">states no value</span>`
      : saw ? `<b class="ok">${esc(who.name.split(" ")[0])} saw it${saw.strength === "weak" ? " (assumed)" : ""}</b>` : `<b class="bad">${esc(who.name.split(" ")[0])} never saw it</b>`;
    return `<tr><td class="num">${r.score.toFixed(2)}</td><td><b>${esc(r.author)}</b> ${esc(r.where)} <span class="muted">${esc(fmtDay(r.ts))}</span><div class="muted">${esc(r.text)}</div></td>
      <td>${r.states == null ? `<span class="muted">no value</span>` : `<span class="vtag ${r.current ? "cur" : "old"}">${esc(fmtVal(r.states))}${r.current ? " (current)" : " (old)"}</span>`}</td><td>${last}</td></tr>`;
  }).join("");
  return `<div class="gvs"><strong>What a vector store returns.</strong> Query <i>"${esc(v.query)}"</i>, embedded with ${esc(v.model)}. It finds the right messages, old and new, ranked by similarity.
    <table class="vtable"><thead><tr><th>Score</th><th>Message</th><th>States</th><th>${who ? "Did " + esc(who.name.split(" ")[0]) + " see it?" : ""}</th></tr></thead><tbody>${rows}</tbody></table>
    The last column is the one that decides who is out of date, and nothing in the store can fill it in. It comes from the SAW edges. Measured on our labelled team: vector RAG F1 0.13 against 0.96.</div>`;
}

function graphBlock(g, focus) {
  const label = S.meta.store === "hydradb" ? "HydraDB" : "the embedded Kuzu store";
  const who = focus ? g.people.find((p) => p.id === focus) : null;
  const miss = who && g.missing.some((x) => x.person === who.id);
  return `
    <div class="kicker" style="margin:0 0 8px">The graph behind this fact</div>
    <div class="gwrap">${graphSvg(g, focus)}</div>
    <div class="glegend">
      <span><i class="l strong"></i> saw it (posted, replied, reacted, mentioned, emailed)</span>
      <span><i class="l weak"></i> assumed: channel member, with a learned read rate</span>
      <span><i class="l missing"></i> no SAW edge to the change</span>
    </div>
    ${who ? `<p class="gnote">${miss && who.stale ? `<strong>${esc(who.name)}</strong> has no edge to the message that changed this fact, so the latest version they hold is <strong>${esc(fmtVal(who.believes))}</strong>. That absence is the signal.`
      : who.in_sync ? `<strong>${esc(who.name)}</strong> saw the change, so they hold the current value.` : `<strong>${esc(who.name)}</strong> has not seen anything about this fact.`}</p>` : `<p class="gnote small muted">Click a person to follow their edges.</p>`}
    ${vectorBlock(g, who)}
    <details class="gcy"><summary>The query behind it · ${g.graph_queries + g.cached_reads} graph reads${g.cached_reads ? ` (${g.cached_reads} already in memory)` : ""}, ${g.ms} ms on ${label}</summary><pre>${esc(g.cypher)}</pre>
      <p class="small muted">Run once per person. SAW edges are written when a message is ingested; fact versions are SelfGraph relations with <code>max_count: 1</code>, so a new value supersedes the old one and keeps it readable.</p></details>`;
}

function renderGraphInto(box, g, focus) {
  box.innerHTML = graphBlock(g, focus);
  box.querySelectorAll(".node.person").forEach((el) => {
    const pick = () => renderGraphInto(box, g, el.dataset.p);
    el.onclick = pick;
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  });
}
