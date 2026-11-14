"use strict";
/* A 60-second guided tour. It drives the real app (time, viewer, dialogs, the pre-send check) rather than showing screenshots. */

const TOUR = { i: -1, hl: null };
const tick = (ms = 350) => new Promise((r) => setTimeout(r, ms));

function tourClear() {
  document.querySelectorAll(".tour-hl").forEach((e) => e.classList.remove("tour-hl"));
}
function tourEnd(seen = true) {
  tourClear();
  $("tour-card").classList.add("hidden");
  TOUR.i = -1;
  closeDlgs();
  document.body.classList.remove("tour-dlg");
  if (seen) { try { localStorage.setItem("unstale-tour-seen", "1"); } catch (e) { /* private mode */ } }
}
async function useViewer(id, ts, tab = "feed") {
  closeDlgs();
  S.viewer = id; S.channel = null; S.draftTo = null; S.draftToIds = null;
  $("check-result").innerHTML = "";
  $("draft").value = "";
  document.querySelector(`.tab[data-tab="${tab}"]`).click();
  renderViewers(); renderChannels(); renderComposeTarget();
  S.asOf = ts;
  const t = d(ts).getTime();
  let best = 0; S.steps.forEach((s, i) => { if (d(s).getTime() <= t) best = i; });
  $("scrub").value = best;
  await refresh();
}

const TOUR_STEPS = [
  { target: ".clock", title: "A team, and one moment",
    run: () => useViewer("person:maya", "2026-06-29T08:55:00Z"),
    text: () => `Northwind Labs is a made-up team of seven people and a support agent. It is <b>${fmtTs(S.asOf)}</b>. Maya, in sales, is about to tell a customer that release 2.4 goes live today. Drag the time bar any time to move around.` },
  { target: ".corrections", title: "What Maya believes that is no longer true",
    text: () => `${esc($("corr-title").textContent)}. Computed by traversing the graph: <b>${esc($("corr-meta").textContent)}</b> No model call, so it costs nothing to do for everyone, every morning.` },
  { target: "#corr-list .card", title: "Not a summary: a correction",
    text: () => `Each one says what she saw, what changed, who changed it and where, and why she missed it. The percentage is how sure the graph is. "News to me" or "I knew this" teaches it who really reads what.` },
  { target: "#slot-dialog", dialog: true, title: "Why it needs a graph",
    run: async () => { const c = document.querySelector("#corr-list .card .linkish"); if (c) await openSlot(c.dataset.open, S.viewer); await tick(200); },
    text: () => `Left to right: who saw which message, and which version of the fact each message states. Maya has <b>no SAW edge</b> to the message that changed the date, so the newest version she can hold is the old one. A vector store returns the same messages but can't say who read which.` },
  { target: "#fix-dialog", dialog: true, title: "Then close the gap",
    run: async () => {
      closeDlgs();
      const c = document.querySelector("#corr-list .card [data-fix]");
      if (c) await openFix(c.dataset.fix);
      await tick(200);
    },
    text: () => `Unstale doesn't stop at detecting. From the same graph and the learned read rates it says who still needs to hear it, which channel reaches them, who needs an @mention because they rarely read that channel, and a draft. "Simulate" shows the corrections that would be left, without writing anything.` },
  { target: "#compose", pos: "tl", title: "Check before sending",
    run: async () => {
      closeDlgs();
      const i = S.meta.drafts.findIndex((x) => x.author === "person:maya");
      document.querySelector(`.preset[data-i="${i}"]`).click(); await tick(900);
      await runCheck();
    },
    text: () => `Her draft says 2.4 goes live today. Unstale flags it as out of date, names the message that changed it, and warns about readers who will believe it. It reads the draft with one model call; the verdict is a graph lookup.` },
  { target: "#agent-block", title: "The same layer for agents",
    run: () => useViewer("agent:support-bot", "2026-07-01T12:00:00Z"),
    text: () => `The support agent reads only its own knowledge-base channel, so it is quoting the old price and refund window. This block goes in front of its prompt, over MCP. In our eval it takes the agent from 29% to 94% correct, with no new access.` },
  { target: "#proof-dialog", dialog: true, title: "The numbers",
    run: async () => { await openProof(); await tick(300); },
    text: () => `Every figure is read from a result file in the repo: labelled team, ${"20"} generated orgs with hidden reading habits, a learning curve on unseen orgs with confidence intervals, and the agent eval, with the limits written out.` },
  { target: ".clock", title: "Your turn",
    run: async () => { closeDlgs(); await useViewer("person:tom", "2026-07-01T08:00:00Z"); },
    text: () => `Click <b>News to me</b> on a correction and watch the graph write it down, then <b>Fix it</b> to see the plan change. Click a fact chip for its graph.${S.meta.mcp ? " Use <b>Connect your agent</b> to point your own agent at this graph." : ""} <b>Pitch</b> has who we think pays, with a calculator.` },
];

async function tourGo(i) {
  if (i < 0 || i >= TOUR_STEPS.length) return tourEnd();
  TOUR.i = i;
  tourClear();
  const st = TOUR_STEPS[i];
  $("tour-card").classList.remove("hidden");
  $("tour-card").dataset.pos = st.pos || "bl";
  document.body.classList.toggle("tour-dlg", !!st.dialog);
  $("tour-title").textContent = st.title;
  $("tour-text").textContent = "...";
  try { if (st.run) await st.run(); } catch (e) { console.error(e); }
  if (TOUR.i !== i) return;
  $("tour-text").innerHTML = st.text();
  $("tour-n").textContent = `${i + 1} of ${TOUR_STEPS.length}`;
  $("tour-prev").disabled = i === 0;
  $("tour-next").textContent = i === TOUR_STEPS.length - 1 ? "Finish" : "Next";
  const el = document.querySelector(st.target);
  if (el && el.tagName !== "DIALOG") { el.classList.add("tour-hl"); el.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}
function tourStart() { tourGo(0); }
$("tour-next").onclick = () => (TOUR.i >= TOUR_STEPS.length - 1 ? tourEnd() : tourGo(TOUR.i + 1));
$("tour-prev").onclick = () => tourGo(TOUR.i - 1);
$("tour-skip").onclick = () => tourEnd();
