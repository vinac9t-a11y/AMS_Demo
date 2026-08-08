// S7 epic intake — page logic. Renders entirely from GET /api/state, same
// pattern as the console: the server owns every rule, this file only draws.

const $ = (id) => document.getElementById(id);

const STREAM_LABELS = {
  frontend: "Frontend", api: "API / Services", database: "Database",
  document_intake: "Document intake", system_of_record: "System of record", test: "Test",
};

let busy = false;

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function scrollToPane(el) {
  if (!el || el.hidden) return;
  // Next frame, so the scroll isn't cancelled by the re-render's layout work.
  requestAnimationFrame(() => {
    el.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
  });
}

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

function setBusy(value, statusEl, message) {
  busy = value;
  document.querySelectorAll("button").forEach((b) => (b.disabled = value));
  document.body.classList.toggle("is-busy", value);
  if (statusEl) {
    statusEl.classList.remove("error");
    if (value) {
      statusEl.innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(message)}`;
    } else {
      statusEl.textContent = "";
    }
  }
}

function showError(statusEl, err) {
  statusEl.classList.add("error");
  statusEl.textContent = err.message;
}

// ---- stage 1: epic in ----------------------------------------------------

$("sampleBtn").addEventListener("click", async () => {
  try {
    const body = await api("/api/sample");
    $("epicText").value = body.text;
    $("epicStatus").textContent = "Seeded epic loaded — EPIC-S7-001.";
  } catch (err) { showError($("epicStatus"), err); }
});

function loadEpicFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    $("epicText").value = reader.result;
    $("epicStatus").classList.remove("error");
    $("epicStatus").textContent = `Loaded ${file.name}.`;
  };
  reader.readAsText(file);
}

$("fileInput").addEventListener("change", (event) => {
  loadEpicFile(event.target.files[0]);
});

// The textarea is also a drop target — dragging a .md straight in beats
// routing through the file picker.
const epicText = $("epicText");
["dragenter", "dragover"].forEach((evt) =>
  epicText.addEventListener(evt, (e) => {
    e.preventDefault();
    epicText.classList.add("drop-hover");
  }));
["dragleave", "drop"].forEach((evt) =>
  epicText.addEventListener(evt, () => epicText.classList.remove("drop-hover")));
epicText.addEventListener("drop", (e) => {
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (!file) return; // plain-text drags keep the browser default
  e.preventDefault();
  loadEpicFile(file);
});

async function runIntake() {
  if (busy) return;
  if (!epicText.value.trim()) {
    showError($("epicStatus"), new Error("Paste an epic first — or load the seeded one."));
    epicText.focus();
    return;
  }
  setBusy(true, $("epicStatus"), "Reading the epic…");
  try {
    const state = await api("/api/epic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: epicText.value }),
    });
    setBusy(false, $("epicStatus"));
    render(state);
    scrollToPane($("clarifyPane"));
  } catch (err) { setBusy(false); showError($("epicStatus"), err); }
}

$("startBtn").addEventListener("click", runIntake);
epicText.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    runIntake();
  }
});

// ---- stage 2: clarify ----------------------------------------------------

$("answerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const answers = [...document.querySelectorAll("#answerFields input")].map((i) => i.value);
  setBusy(true, $("clarifyStatus"), "Thinking…");
  try {
    const state = await api("/api/answers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    });
    setBusy(false, $("clarifyStatus"));
    render(state);
    // The response is either the plan or another question round — either way
    // the new content is what the user should be looking at.
    scrollToPane(state.status === "planned" ? $("planPane") : $("answerForm"));
  } catch (err) { setBusy(false); showError($("clarifyStatus"), err); }
});

// Blank answers become stated assumptions; say how many, live, before send.
$("answerFields").addEventListener("input", updateAnswerHint);

function updateAnswerHint() {
  const inputs = [...document.querySelectorAll("#answerFields input")];
  const hint = $("answerHint");
  if (!inputs.length) { hint.textContent = ""; return; }
  const filled = inputs.filter((i) => i.value.trim()).length;
  hint.classList.toggle("ok", filled === inputs.length);
  hint.textContent = filled === inputs.length
    ? `All ${inputs.length} answered.`
    : `${filled} of ${inputs.length} answered — blanks become stated assumptions.`;
}

$("skipBtn").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true, $("clarifyStatus"), "Planning from what is known…");
  try {
    const state = await api("/api/skip", { method: "POST" });
    setBusy(false, $("clarifyStatus"));
    render(state);
    scrollToPane($("planPane"));
  } catch (err) { setBusy(false); showError($("clarifyStatus"), err); }
});

// Reset throws the session away, so it asks twice — inline on the button,
// because a browser confirm() would block the page.
let resetConfirmTimer = null;
$("resetBtn").addEventListener("click", async () => {
  if (busy) return;
  const btn = $("resetBtn");
  if (!btn.classList.contains("confirming")) {
    btn.classList.add("confirming");
    btn.textContent = "Confirm reset";
    resetConfirmTimer = setTimeout(() => {
      btn.classList.remove("confirming");
      btn.textContent = "Reset";
    }, 4000);
    return;
  }
  clearTimeout(resetConfirmTimer);
  btn.classList.remove("confirming");
  btn.textContent = "Reset";
  const statusEl = $("epicPane").hidden ? $("clarifyStatus") : $("epicStatus");
  try {
    render(await api("/api/reset", { method: "POST" }));
    scrollToPane($("epicPane"));
  } catch (err) { showError(statusEl, err); }
});

// The stepper doubles as navigation once its pane is on screen.
[["step1", "epicPane"], ["step2", "clarifyPane"], ["step3", "planPane"]]
  .forEach(([stepId, paneId]) => {
    $(stepId).addEventListener("click", () => scrollToPane($(paneId)));
  });

// ---- rendering -----------------------------------------------------------

function esc(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

function setStep(n, state) {
  const el = $("step" + n);
  el.classList.toggle("active", state === "active");
  el.classList.toggle("done", state === "done");
}

let toastTimer = null;
function toast(message, isError) {
  const node = $("toast");
  node.textContent = message;
  node.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2800);
}

function render(state) {
  const planned = state.status === "planned";
  const clarifying = state.status === "clarifying";
  // Story cards are rebuilt on every state change; carry the open/closed
  // state of their detail folds across the rebuild.
  const openDetails = [...document.querySelectorAll("#sprints .story details[open]")]
    .map((d) => d.closest(".story").dataset.sid);

  $("epicPane").hidden = state.status !== "empty";
  $("clarifyPane").hidden = state.status === "empty";
  $("planPane").hidden = !planned;
  setStep(1, state.status === "empty" ? "active" : "done");
  setStep(2, clarifying ? "active" : planned ? "done" : "");
  setStep(3, planned ? "active" : "");
  $("step1").classList.toggle("clickable", !$("epicPane").hidden);
  $("step2").classList.toggle("clickable", !$("clarifyPane").hidden);
  $("step3").classList.toggle("clickable", !$("planPane").hidden);

  const badge = $("roundsBadge");
  badge.hidden = state.status === "empty";
  badge.textContent = `question rounds: ${state.rounds_used ?? 0} / ${state.max_rounds}`;

  if (state.status === "empty") {
    $("activityList").innerHTML = "";
    $("reviewLogWrap").hidden = true;
    return;
  }

  $("epicTitle").textContent = state.epic_title;
  renderChat(state);
  renderActivity(state.activity);
  renderReviewLog(state.review_log);
  if (planned) {
    renderPlan(state);
    openDetails.forEach((sid) => {
      const fold = document.querySelector(`.story[data-sid="${sid}"] details`);
      if (fold) fold.open = true;
    });
  }
}

function renderChat(state) {
  const chat = $("chat");
  chat.innerHTML = "";
  for (const turn of state.transcript) {
    const isUser = turn.role === "user";
    // Open questions render as the answer form instead of a bubble.
    if (!isUser && state.questions.length &&
        turn === state.transcript[state.transcript.length - 1]) continue;
    const div = document.createElement("div");
    div.className = "bubble " + (isUser ? "user" : "ai");
    div.innerHTML = `<span class="who">${isUser ? "You" : "AI intake"}</span>${esc(turn.text)}`;
    chat.appendChild(div);
  }

  const form = $("answerForm");
  const fields = $("answerFields");
  form.hidden = !state.questions.length;
  fields.innerHTML = "";
  state.questions.forEach((q, i) => {
    const wrap = document.createElement("div");
    wrap.className = "q-field";
    wrap.innerHTML =
      `<label for="ans${i}">${esc(q)}</label>` +
      `<input id="ans${i}" type="text" placeholder="Answer — or leave blank to let it assume">`;
    fields.appendChild(wrap);
  });
  if (state.questions.length) {
    fields.querySelector("input").focus({ preventScroll: true });
  }
  updateAnswerHint();
}

function renderPlan(state) {
  const plan = state.plan;
  const draft = state.plan_status === "draft";
  $("planTitle").textContent = state.epic_title;
  $("planBadge").textContent = plan.provenance === "live_ai" ? "LIVE AI" : "REPLAYED AI";
  const stateBadge = $("planState");
  stateBadge.textContent = draft ? "DRAFT — under human review" : "APPROVED — locked";
  stateBadge.className = "badge state " + (draft ? "draft" : "approved");

  // Requirement coverage — computed server-side, rendered honestly.
  const byReq = {};
  for (const story of plan.stories) {
    for (const rid of story.satisfies) (byReq[rid] = byReq[rid] || []).push(story.id);
  }
  const unmapped = plan.unmapped_requirements;
  const rows = plan.requirements.map((r) => {
    const by = byReq[r.id] ? byReq[r.id].join(", ") : "— NOT COVERED";
    return `<div class="cover-row"><span class="rid">${esc(r.id)}</span>` +
      `<span class="rtext">${esc(r.text)}</span><span class="rby">${esc(by)}</span></div>`;
  }).join("");
  $("coverage").innerHTML =
    `<div class="panel ${unmapped.length ? "bad" : ""}">` +
    `<h4>Requirement coverage ${unmapped.length
      ? `— ${unmapped.length} NOT COVERED` : "— complete"}</h4>${rows}</div>`;

  $("assumptions").innerHTML = plan.assumptions.length
    ? `<div class="panel warn"><h4>Assumptions carried, not answered</h4>` +
      `<ul>${plan.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`
    : "";

  // Which sprint holds each story, and which stories a human has touched.
  const sprintOf = {};
  plan.sprints.forEach((sp) => sp.story_ids.forEach((sid) => { sprintOf[sid] = sp.id; }));
  const humanTouched = new Set(
    (state.review_log || []).map((e) => e.story_id).filter(Boolean)
  );

  const stories = Object.fromEntries(plan.stories.map((s) => [s.id, s]));
  $("sprints").innerHTML = plan.sprints.map((sprint) => {
    const cards = sprint.story_ids
      .map((sid) => storyCard(stories[sid], state, draft, sprintOf, humanTouched))
      .join("");
    return `<div class="sprint"><div class="sprint-head"><h3>${esc(sprint.id)}</h3>` +
      `<span class="goal">${esc(sprint.goal)}</span></div>` +
      `<div class="cards">${cards}</div></div>`;
  }).join("");

  renderReview(state);

  const total = Object.values(plan.points_by_assignee).reduce((a, b) => a + b, 0) || 1;
  $("teamLoad").innerHTML = state.team.map((member) => {
    const pts = plan.points_by_assignee[member.name] || 0;
    const share = Math.round((pts / total) * 100);
    const over = pts / total > 0.5;
    return `<div class="load-card ${over ? "over" : ""}"` +
      `${over ? ' title="Carrying more than half the plan — the roster rule says spread the points"' : ""}>` +
      `<b>${esc(member.name)}</b>` +
      `<span class="t">${esc(member.title)}</span>` +
      `<span class="pts">${pts} pts · ${share}%${over ? " ⚠" : ""}</span></div>`;
  }).join("");
}

function storyCard(story, state, draft, sprintOf, humanTouched) {
  if (!story) return "";
  const chips =
    (draft ? "" : `<span class="chip owner">${esc(story.assignee)}</span>`) +
    `<span class="chip">${esc(story.task_type)}</span>` +
    story.streams.map((s) => `<span class="chip">${esc(STREAM_LABELS[s] || s)}</span>`).join("") +
    (story.feature_flag ? `<span class="chip flag">flag: ${esc(story.feature_flag)}</span>` : "") +
    (humanTouched.has(story.id) ? `<span class="chip human">human-shaped</span>` : "");
  const ac = story.acceptance.map((c) => `<li><b>${esc(c.id)}</b> — ${esc(c.text)}</li>`).join("");
  const deps = story.depends_on.length ? story.depends_on.join(", ") : "none";
  const assume = story.assumptions.length
    ? `<div class="assume">Assumes: ${story.assumptions.map(esc).join(" · ")}</div>` : "";
  return `<div class="story" data-sid="${esc(story.id)}">
    <div class="head"><span class="sid">${esc(story.id)}</span>
      ${draft ? "" : `<span class="pts">${story.estimate_points} pts</span>`}</div>
    <div class="title">${esc(story.title)}</div>
    <div class="narrative">${esc(story.narrative)}</div>
    <div class="meta">${chips}</div>
    ${draft ? storyControls(story, state, sprintOf) : ""}
    <details><summary>Acceptance · component · rollback</summary>
      <div class="kv">
        <b>Component</b><span>${esc(story.target_component)}</span>
        <b>Impacts</b><span>${esc(story.impacts)}</span>
        <b>Rollback</b><span>${esc(story.rollback_plan)}</span>
        <b>Depends on</b><span>${esc(deps)}</span>
        <b>Satisfies</b><span>${esc(story.satisfies.join(", ") || "—")}</span>
      </div>
      <ul class="ac">${ac}</ul>
    </details>
    ${assume}
  </div>`;
}

// The reviewer's per-story controls. Options mirror the engine's rules —
// only stream-eligible leads are offered — and the server re-checks anyway.
function storyControls(story, state, sprintOf) {
  const eligible = state.team.filter(
    (m) => m.streams.some((s) => story.streams.includes(s))
  );
  const leadOpts = eligible.map((m) =>
    `<option value="${esc(m.name)}"${m.name === story.assignee ? " selected" : ""}>` +
    `${esc(m.name)}</option>`).join("");
  const ptOpts = (state.point_scale || []).map((p) =>
    `<option value="${p}"${p === story.estimate_points ? " selected" : ""}>${p} pts</option>`
  ).join("");
  const spOpts = state.plan.sprints.map((sp) =>
    `<option value="${esc(sp.id)}"${sprintOf[story.id] === sp.id ? " selected" : ""}>` +
    `${esc(sp.id)}</option>`).join("");
  return `<div class="controls">
    <label>Lead <select data-act="reassign" data-story="${esc(story.id)}">${leadOpts}</select></label>
    <label>Estimate <select data-act="points" data-story="${esc(story.id)}">${ptOpts}</select></label>
    <label>Sprint <select data-act="move" data-story="${esc(story.id)}">${spOpts}</select></label>
  </div>`;
}

// One delegated listener survives every re-render of the cards.
$("sprints").addEventListener("change", async (event) => {
  const sel = event.target.closest("select[data-act]");
  if (!sel || busy) return;
  const sid = sel.dataset.story;
  const paths = {
    reassign: "/api/plan/reassign",
    points: "/api/plan/points",
    move: "/api/plan/move",
  };
  const bodies = {
    reassign: { story_id: sid, assignee: sel.value },
    points: { story_id: sid, points: Number(sel.value) },
    move: { story_id: sid, sprint_id: sel.value },
  };
  const act = sel.dataset.act;
  try {
    busy = true;
    const state = await api(paths[act], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodies[act]),
    });
    busy = false;
    render(state);
    toast(`${sid} updated — logged in the review trail.`);
  } catch (err) {
    busy = false;
    toast(err.message, true);
    render(await api("/api/state")); // put the select back to the server's truth
  }
});

function renderReview(state) {
  const container = $("review");
  if (state.plan_status === "approved") {
    const a = state.approval || {};
    container.innerHTML =
      `<div class="panel approved-panel"><h4>Plan approved &amp; locked</h4>` +
      `<p>Signed off by <b>${esc(a.by)}</b> at ${esc(a.at)}.` +
      `${a.note ? ` — “${esc(a.note)}”` : ""}</p>` +
      `<p class="soft">Edits are locked. Reset the session to start a new run.</p></div>`;
    return;
  }

  container.innerHTML = `<div class="panel review-panel">
    <h4>Human review — shape the draft, then sign off</h4>
    <p class="soft">Reassign leads, re-estimate and move stories directly on the
    cards above. Or send the whole draft back with feedback — the AI revises,
    and the same rules re-check the result.</p>
    <div class="revise-row">
      <textarea id="feedbackText" rows="2"
        placeholder="What should change? e.g. 'S7-INT-4 is underestimated, and status tracking belongs in Sprint 1'"></textarea>
      <div class="revise-side">
        <button id="reviseBtn" type="button">Request AI revision</button>
        <span class="soft">revisions: ${state.revisions_used} / ${state.max_revisions}</span>
      </div>
    </div>
    <div class="approve-row">
      <input id="approverName" placeholder="Approver name (required)" autocomplete="name">
      <input id="approveNote" placeholder="Sign-off note (optional)">
      <button id="approveBtn" class="primary" type="button" disabled>Approve &amp; lock plan</button>
    </div>
    <span id="reviewStatus" class="status" role="status" aria-live="polite"></span>
  </div>`;

  const name = $("approverName");
  const approve = $("approveBtn");
  name.addEventListener("input", () => { approve.disabled = !name.value.trim(); });

  $("reviseBtn").addEventListener("click", async () => {
    if (busy) return;
    const feedback = $("feedbackText").value.trim();
    if (feedback.length < 10) {
      showError($("reviewStatus"), new Error("Say what should change — a sentence, not a word."));
      return;
    }
    setBusy(true, $("reviewStatus"), "Revising the plan — same validator, fresh draft…");
    try {
      const next = await api("/api/plan/revise", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      });
      setBusy(false);
      render(next);
      scrollToPane($("planPane"));
      toast("Revised plan passed validation and re-rendered.");
    } catch (err) { setBusy(false); showError($("reviewStatus"), err); }
  });

  approve.addEventListener("click", async () => {
    if (busy) return;
    setBusy(true, $("reviewStatus"), "Recording the sign-off…");
    try {
      const next = await api("/api/plan/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approver: name.value, note: $("approveNote").value }),
      });
      setBusy(false);
      render(next);
      toast(`Plan approved and locked.`);
    } catch (err) { setBusy(false); showError($("reviewStatus"), err); }
  });
}

function renderReviewLog(entries) {
  const wrap = $("reviewLogWrap");
  const has = Boolean(entries && entries.length);
  wrap.hidden = !has;
  if (!has) { $("reviewLog").innerHTML = ""; return; }
  $("reviewLog").innerHTML = entries.map((e) =>
    `<div class="act-entry"><b>${esc(e.action)}</b> at ${esc(e.at)}<br>${esc(e.detail)}</div>`
  ).join("");
}

function renderActivity(entries) {
  $("activityList").innerHTML = (entries || []).map((e) => {
    const tokens = e.input_tokens
      ? ` · ${e.input_tokens.toLocaleString()} in / ${(e.output_tokens || 0).toLocaleString()} out`
      : "";
    return `<div class="act-entry"><b>${esc(e.beat)}</b> at ${esc(e.at)}<br>` +
      `${e.seconds}s${tokens}<br><span class="prov">${esc(e.provenance)}</span></div>`;
  }).join("");
}

// ---- boot ----------------------------------------------------------------

api("/api/state").then(render).catch((err) => showError($("epicStatus"), err));
