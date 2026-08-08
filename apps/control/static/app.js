/* S7 Delivery Control Centre — renders entirely from the run-state payload.
   No rule lives here: buttons reflect permissions and gate state, the server
   enforces them. Sections not yet implemented by the engine render an honest
   "not built in this phase" panel rather than a mock. */

(() => {
  "use strict";

  const API = "";
  const state = {
    runId: localStorage.getItem("s7cc.runId") || null,
    role: localStorage.getItem("s7cc.role") || "delivery_lead",
    section: localStorage.getItem("s7cc.section") || "overview",
    data: null,
    roles: [],
    workspace: null,
    workspaceAssignee: localStorage.getItem("s7cc.workspaceAssignee") || "",
  };

  const $ = (id) => document.getElementById(id);
  const main = $("main");

  // --- tiny dom helpers ----------------------------------------------------

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const child of children.flat()) {
      if (child == null) continue;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function badge(status) {
    return el("span", { class: `badge st-${status}`, text: String(status).replaceAll("_", " ") });
  }

  function prov(p) {
    return p ? el("span", { class: `prov prov-${p}`, text: p.toUpperCase() }) : null;
  }

  function toast(message, isError = false) {
    const t = $("toast");
    t.textContent = message;
    t.classList.toggle("error", isError);
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), 3200);
  }

  // --- api -----------------------------------------------------------------

  async function api(path, options = {}) {
    const res = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* text body */ }
      throw new Error(detail);
    }
    return res.json();
  }

  async function ensureRun() {
    const runs = await api("/api/runs");
    if (state.runId && runs.includes(state.runId)) return;
    if (runs.length) {
      state.runId = runs[runs.length - 1];
    } else {
      const created = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify({ mode: "simulation" }),
      });
      state.runId = created.run.run_id;
    }
    localStorage.setItem("s7cc.runId", state.runId);
  }

  async function refresh() {
    try {
      await ensureRun();
      state.data = await api(`/api/runs/${state.runId}`);
      render();
    } catch (err) {
      toast(`Could not load run state: ${err.message}`, true);
    }
  }

  async function act(path, body = {}, okMessage = "Done", method = "POST") {
    try {
      state.data = await api(`/api/runs/${state.runId}${path}`, {
        method,
        body: JSON.stringify({ role: state.role, ...body }),
      });
      render();
      toast(okMessage);
    } catch (err) {
      toast(err.message, true);
    }
  }

  // --- chrome --------------------------------------------------------------

  const STAGES = [
    ["intake", "Intake"],
    ["planning", "Planning"],
    ["build_review", "Build & Review"],
    ["quality", "Quality"],
    ["release", "Release"],
  ];

  const NAV = [
    ["nav-run", "Run"],
    ["overview", "Overview"],
    ["intake", "Intake"],
    ["planning", "Planning"],
    ["build_review", "Build & Review"],
    ["quality", "Quality"],
    ["release", "Release"],
    ["nav-detail", "Detail"],
    ["stories", "Epics & Stories"],
    ["work", "Work Queue"],
    ["workspace", "My Workspace"],
    ["traceability", "Traceability"],
    ["artifacts", "Artifacts"],
    ["approvals", "Approvals"],
    ["nav-gov", "Governance"],
    ["activity", "Activity Log"],
    ["provenance", "Provenance"],
    ["risks", "Risks & Alerts"],
    ["reports", "Reports"],
    ["settings", "Settings"],
  ];

  function renderChrome() {
    const run = state.data?.run;
    $("modePill").textContent = `mode: ${run?.mode ?? "—"}`;
    $("runPill").textContent = `run: ${run?.run_id ?? "—"}`;

    const roleSel = $("roleSelect");
    if (roleSel.options.length === 0) {
      for (const r of state.roles) {
        roleSel.appendChild(el("option", { value: r.role, text: r.role.replaceAll("_", " ") }));
      }
      roleSel.value = state.role;
      roleSel.addEventListener("change", () => {
        state.role = roleSel.value;
        localStorage.setItem("s7cc.role", state.role);
        render();
      });
    }

    const stepper = $("stepper");
    stepper.replaceChildren();
    (run?.stages ?? []).forEach((s, i) => {
      if (i > 0) stepper.appendChild(el("span", { class: "step-arrow", text: "→" }));
      const label = STAGES.find(([k]) => k === s.stage)?.[1] ?? s.stage;
      stepper.appendChild(
        el("button", {
          class: `step ${s.status}`,
          onclick: () => go(s.stage),
        },
          el("span", { class: "dot", text: String(i + 1) }),
          label,
          el("span", { class: `badge st-${s.status}`, text: s.status.replaceAll("_", " ") }),
        )
      );
    });

    const nav = $("sidenav");
    nav.replaceChildren();
    for (const [key, label] of NAV) {
      if (key.startsWith("nav-")) {
        nav.appendChild(el("div", { class: "nav-group", text: label }));
        continue;
      }
      nav.appendChild(
        el("button", {
          class: key === state.section ? "active" : "",
          text: label,
          onclick: () => go(key),
        })
      );
    }
  }

  function go(section) {
    state.section = section;
    localStorage.setItem("s7cc.section", section);
    render();
  }

  // --- sections ------------------------------------------------------------

  function sectionTitle(title, hint) {
    return el("div", { class: "section-title" },
      el("h2", { text: title }),
      hint ? el("span", { class: "hint", text: hint }) : null,
    );
  }

  function notBuilt(name, phase) {
    return el("section", {},
      sectionTitle(name),
      el("div", { class: "card warn" },
        el("h3", { text: "Not built in this phase" }),
        el("p", { text: `${name} lands in ${phase} of the implementation plan. ` +
          "This panel is a placeholder, deliberately not a mock — nothing on " +
          "this surface pretends to be evidence it does not have." }),
      ),
    );
  }

  function renderOverview() {
    const d = state.data;
    const run = d.run;
    const summary = d.activity_summary ?? {};
    const counters = summary.counters ?? {};

    return el("section", {},
      sectionTitle("Delivery overview", d.scenario?.title ?? ""),
      el("div", { class: "grid cols-4" },
        el("div", { class: "card metric" },
          el("div", { class: "v", text: String(d.provenance?.length ?? 0) }),
          el("div", { class: "l", text: "Artifacts" })),
        el("div", { class: "card metric" },
          el("div", { class: "v", text: String(counters.human_approvals ?? 0) }),
          el("div", { class: "l", text: "Human approvals" })),
        el("div", { class: "card metric" },
          el("div", { class: "v", text: String(counters.gate_failures ?? 0) }),
          el("div", { class: "l", text: "Gate failures" })),
        el("div", { class: "card metric" },
          el("div", { class: "v", text: String(summary.total_events ?? 0) }),
          el("div", { class: "l", text: "Activity events" })),
      ),
      sectionTitle("Gates", "Progress is a set of explicit conditions, never a score"),
      el("div", { class: "gate-strip" },
        (d.gates ?? []).map((g) =>
          el("div", { class: "gate-card" },
            el("div", { class: "gid", text: g.gate_id }),
            el("div", { class: "glabel", text: g.label }),
            badge(g.status),
            g.decided_by ? el("div", { class: "hint", text: `by ${g.decided_by}` }) : null,
          )
        ),
      ),
      sectionTitle("Scenario"),
      el("div", { class: "card" },
        el("div", { class: "kv" },
          el("b", { text: "Scenario" }), el("span", { text: d.scenario?.title ?? "—" }),
          el("b", { text: "Description" }), el("span", { text: d.scenario?.description ?? "—" }),
          el("b", { text: "Epic source" }), el("code", { text: d.scenario?.epic_source ?? "—" }),
          el("b", { text: "Run created" }), el("span", { text: run.created_at }),
        ),
      ),
    );
  }

  function renderIntake() {
    const d = state.data;
    const req = d.intake?.requirement;
    const analysis = d.intake?.analysis;
    const epic = d.intake?.epic;

    const parts = [sectionTitle("Stage 1 — Intake", "Requirement capture, AI analysis, epic creation")];

    if (req) {
      parts.push(el("div", { class: "card highlight" },
        el("div", { class: "section-title" }, el("h3", { text: "Requirement summary" }), prov(req.provenance)),
        el("div", { class: "kv" },
          el("b", { text: "Request" }), el("span", { class: "mono", text: req.request_id }),
          el("b", { text: "Title" }), el("span", { text: req.title }),
          el("b", { text: "Business owner" }), el("span", { text: req.business_owner }),
          el("b", { text: "Domain" }), el("span", { text: req.domain }),
          el("b", { text: "Priority" }), el("span", { text: req.priority }),
          el("b", { text: "Requested" }), el("span", { text: req.requested_date }),
          el("b", { text: "Target release" }), el("span", { text: req.target_release }),
          el("b", { text: "Description" }), el("span", { text: req.description }),
        ),
      ));
    }

    if (analysis) {
      parts.push(el("div", { class: "card" },
        el("div", { class: "section-title" }, el("h3", { text: "AI intake analysis" }), prov(analysis.provenance)),
        el("div", { class: "kv" },
          el("b", { text: "Business impact" }), el("span", { text: analysis.business_impact }),
          el("b", { text: "Affected applications" }),
          el("span", {}, el("ul", { class: "plain" }, analysis.affected_applications.map((a) => el("li", { text: a })))),
          el("b", { text: "Dependencies" }),
          el("span", {}, el("ul", { class: "plain" }, analysis.dependencies.map((a) => el("li", { text: a })))),
          el("b", { text: "Risks" }),
          el("span", {}, el("ul", { class: "plain" }, analysis.risks.map((a) => el("li", { text: a })))),
          el("b", { text: "Open questions (SME)" }),
          el("span", {}, el("ul", { class: "plain" }, analysis.clarification_questions.map((a) => el("li", { text: a })))),
          el("b", { text: "Assumptions" }),
          el("span", {}, el("ul", { class: "plain" }, analysis.assumptions.map((a) => el("li", { text: a })))),
        ),
      ));
    }

    if (epic) {
      parts.push(el("div", { class: "card ok" },
        el("div", { class: "section-title" }, el("h3", { text: "Created epic" }), prov(epic.provenance)),
        el("div", { class: "kv" },
          el("b", { text: "Epic" }), el("span", { class: "mono", text: epic.epic_id }),
          el("b", { text: "Title" }), el("span", { text: epic.title }),
          el("b", { text: "Business outcome" }), el("span", { text: epic.business_outcome }),
          el("b", { text: "Estimated stories" }), el("span", { text: String(epic.estimated_stories) }),
          el("b", { text: "Created by" }), el("span", { text: epic.created_by }),
        ),
      ));
    }

    const gate = (d.gates ?? []).find((g) => g.gate_id === "G0");
    parts.push(el("div", { class: "card" },
      el("div", { class: "section-title" }, el("h3", { text: "Intake gate (G0)" }), badge(gate?.status ?? "not_started")),
      el("ul", { class: "plain" },
        (gate?.conditions ?? []).map((c) =>
          el("li", {}, `${c.met ? "✓" : "✗"} ${c.condition}`, c.detail ? el("span", { class: "hint", text: ` — ${c.detail}` }) : null)),
      ),
      el("div", { class: "actions-row" },
        el("button", { class: "primary", text: "Run intake analysis", onclick: () => act("/intake/analyse", {}, "Intake analysis complete") }),
        el("button", { class: "primary", text: "Create epic", onclick: () => act("/intake/create-epic", {}, "Epic created") }),
        el("button", { class: "primary approve", text: "Pass intake gate", onclick: () => act("/intake/pass-gate", {}, "Intake gate passed") }),
      ),
    ));

    return el("section", {}, parts);
  }

  const RENDERERS = {
    overview: renderOverview,
    intake: renderIntake,
    planning: renderPlanning,
    build_review: renderBuildReview,
    quality: renderQuality,
    release: renderRelease,
    stories: renderStories,
    work: renderWorkQueue,
    workspace: renderWorkspace,
    traceability: renderTraceability,
    artifacts: renderArtifacts,
    approvals: renderApprovals,
    activity: renderActivity,
    provenance: renderProvenance,
    risks: renderRisks,
    reports: renderReports,
    settings: renderSettings,
  };

  const TEAMS = ["Portal Team", "Services Team", "Data Team",
    "Intake Integration Team", "QA Automation", "Platform Team", "Support Team"];

  function renderPlanning() {
    const d = state.data;
    const stories = d.planning?.stories ?? [];
    const plan = d.planning?.plan;
    const locked = d.run.plan_locked;
    const gate = (d.gates ?? []).find((g) => g.gate_id === "G1");

    const parts = [sectionTitle("Stage 2 — Planning",
      "Epic decomposed into testable stories, each with one accountable team")];

    if (stories.length === 0) {
      parts.push(el("div", { class: "card" },
        el("p", { text: "No plan yet. Decomposition opens once the intake gate (G0) has passed." }),
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Generate draft plan",
            onclick: () => act("/planning/generate", {}, "Draft plan generated") })),
      ));
      return el("section", {}, parts);
    }

    const acs = stories.flatMap((s) => s.acceptance_criteria);
    const deps = stories.flatMap((s) => s.dependencies);
    const teams = [...new Set(stories.map((s) => s.accountable_team))];
    const sprints = [...new Set(stories.map((s) => s.sprint))];

    parts.push(el("div", { class: "grid cols-4" },
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(stories.length) }), el("div", { class: "l", text: "Stories" })),
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(teams.length) }), el("div", { class: "l", text: "Teams" })),
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(acs.length) }), el("div", { class: "l", text: "Acceptance criteria" })),
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(sprints.length) }), el("div", { class: "l", text: "Sprints" })),
    ));

    // routing table with inline reviewer controls (spec §8B/§8F)
    const editable = !locked;
    parts.push(sectionTitle("Story routing",
      locked ? "Plan locked at sign-off — edits require an amendment" : "Editable until Gate 1 sign-off locks the plan"));
    parts.push(el("div", { class: "table-wrap" },
      el("table", {},
        el("thead", {}, el("tr", {},
          ["Story", "Title", "Accountable team", "Owner", "Component", "Depends on", "Est", "Sprint", "Risk", "Quality"].map((h) => el("th", { text: h })))),
        el("tbody", {}, stories.map((s) => {
          const gaps = storyGaps(s);
          return el("tr", {},
            el("td", { class: "mono", text: s.story_id }),
            el("td", { text: s.title }),
            el("td", {}, editable
              ? el("select", { onchange: (e) => act(`/stories/${s.story_id}`, { patch: { accountable_team: e.target.value } }, `${s.story_id} reassigned`, "PATCH") },
                TEAMS.map((t) => Object.assign(el("option", { value: t, text: t }), { selected: t === s.accountable_team })))
              : el("span", { text: s.accountable_team })),
            el("td", {}, editable
              ? el("input", {
                  type: "text", value: s.owner || "", placeholder: "unassigned",
                  onchange: (e) => act(`/stories/${s.story_id}`, { patch: { owner: e.target.value.trim() } }, `${s.story_id} owner set`, "PATCH"),
                })
              : el("span", { text: s.owner || "—" })),
            el("td", { text: s.target_component }),
            el("td", { class: "mono", text: s.dependencies.join(", ") || "—" }),
            el("td", {}, editable
              ? el("select", { onchange: (e) => act(`/stories/${s.story_id}`, { patch: { estimate: Number(e.target.value) } }, `${s.story_id} re-estimated`, "PATCH") },
                [3, 5, 8, 13].map((n) => Object.assign(el("option", { value: String(n), text: `${n} pts` }), { selected: n === s.estimate })))
              : el("span", { text: `${s.estimate} pts` })),
            el("td", {}, editable
              ? el("select", { onchange: (e) => act(`/stories/${s.story_id}`, { patch: { sprint: Number(e.target.value) } }, `${s.story_id} moved`, "PATCH") },
                [1, 2, 3].map((n) => Object.assign(el("option", { value: String(n), text: `S${n}` }), { selected: n === s.sprint })))
              : el("span", { text: `S${s.sprint}` })),
            el("td", { text: s.risk }),
            el("td", {}, gaps.length === 0 ? badge("passed") : el("span", { class: "badge st-blocked", title: gaps.join("; "), text: `${gaps.length} gaps` })),
          );
        })),
      ),
    ));

    // dependency chain + routing by team
    parts.push(el("div", { class: "grid cols-2", style: "margin-top:14px" },
      el("div", { class: "card" },
        el("h3", { text: "Dependency chain" }),
        el("ul", { class: "plain" }, stories.map((s) =>
          el("li", {}, el("span", { class: "mono", text: s.story_id }),
            s.dependencies.length ? ` ← depends on ${s.dependencies.join(", ")}` : " — no upstream dependency"))),
      ),
      el("div", { class: "card" },
        el("h3", { text: "Routing by team" }),
        el("ul", { class: "plain" }, teams.map((t) => {
          const n = stories.filter((s) => s.accountable_team === t).length;
          return el("li", {}, `${t}: ${n} ${n === 1 ? "story" : "stories"}`);
        })),
      ),
    ));

    // revision + gate 1
    if (!locked) {
      const fb = el("textarea", { rows: "2", placeholder: "What should change? e.g. 'US-004 is underestimated; move status visibility into Sprint 1'" });
      parts.push(el("div", { class: "card", style: "margin-top:14px" },
        el("h3", { text: "Request AI revision" }),
        el("p", { class: "hint", text: "Records the revision request in the activity log. In simulation mode the draft is revised deterministically." }),
        fb,
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Request revision",
            onclick: () => act("/planning/revise", { feedback: fb.value }, "Revision requested") })),
      ));
    }

    const approver = el("input", { type: "text", placeholder: "Approver name (required)" });
    const note = el("input", { type: "text", placeholder: "Sign-off note (optional)" });
    parts.push(el("div", { class: `card ${gate?.status === "passed" ? "ok" : "highlight"}`, style: "margin-top:14px" },
      el("div", { class: "section-title" },
        el("h3", { text: "Gate 1 — Plan sign-off" }), badge(gate?.status ?? "not_started")),
      (gate?.conditions ?? []).length
        ? el("ul", { class: "plain" }, gate.conditions.map((c) =>
          el("li", {}, `${c.met ? "✓" : "✗"} ${c.condition}`,
            c.detail ? el("span", { class: "hint", text: ` — ${c.detail}` }) : null)))
        : el("p", { class: "hint", text: "Conditions evaluate at sign-off. Only the Business Owner role may sign." }),
      plan
        ? el("div", { class: "kv", style: "margin-top:10px" },
          el("b", { text: "Signed by" }), el("span", { text: plan.signed_by }),
          el("b", { text: "At" }), el("span", { class: "mono", text: plan.signed_at }),
          el("b", { text: "Plan version" }), el("span", { text: `v${plan.plan_version}` }),
          el("b", { text: "Contract" }), el("code", { text: "planning/plan.json · planning/plan.md" }))
        : el("div", {},
          el("label", { class: "fld", text: "Approver" }), approver,
          el("label", { class: "fld", text: "Note" }), note,
          el("div", { class: "actions-row" },
            el("button", { class: "primary approve", text: "Approve & lock plan",
              onclick: () => act("/planning/sign-off", { approver: approver.value, note: note.value }, "Plan signed and locked") }))),
    ));

    return el("section", {}, parts);
  }

  function workQueueTable(tasks, onSelect) {
    return el("div", { class: "table-wrap" },
      el("table", {},
        el("thead", {}, el("tr", {},
          ["Task", "Story", "Summary", "Team", "Owner", "Depends on", "Progress", "Status", "Last activity"].map((h) => el("th", { text: h })))),
        el("tbody", {}, tasks.map((t) =>
          el("tr", { style: onSelect ? "cursor:pointer" : "", onclick: onSelect ? () => onSelect(t.task_id) : undefined },
            el("td", { class: "mono", text: t.task_id }),
            el("td", { class: "mono", text: t.story_id }),
            el("td", { text: t.summary }),
            el("td", { text: t.accountable_team || "—" }),
            el("td", { text: t.owner || "—" }),
            el("td", { class: "mono", text: (t.dependencies ?? []).join(", ") || "—" }),
            el("td", { text: `${t.progress_pct}%` }),
            el("td", {}, badge(t.status)),
            el("td", { class: "mono", text: t.last_activity || "—" }),
          ))),
      ),
    );
  }

  function renderWorkQueue() {
    const tasks = state.data.build?.tasks ?? [];
    if (!tasks.length) return notBuilt("Work Queue", "the Planning stage — the queue is seeded when the plan is signed");
    const buckets = ["ready", "in_progress", "waiting_for_approval", "blocked", "completed", "not_started"];
    return el("section", {},
      sectionTitle("Work queue", "Seeded from the signed plan; one task processed at a time"),
      el("div", { class: "grid cols-4" }, buckets.slice(0, 4).map((b) =>
        el("div", { class: "card metric" },
          el("div", { class: "v", text: String(tasks.filter((t) => t.status === b).length) }),
          el("div", { class: "l", text: b.replaceAll("_", " ") })))),
      el("div", { style: "margin-top:14px" }, workQueueTable(tasks, (id) => { state.taskId = id; go("build_review"); })),
    );
  }

  // --- workspace (per-assignee handoff) -------------------------------------

  function jsSlug(name) {
    // Mirrors s7_delivery.factory.workspace.slugify — display-only preview
    // of the path the server actually writes to; the server is authoritative.
    let slug = String(name).trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
    if (!slug) slug = "unassigned";
    if (!/^[a-z0-9]/.test(slug)) slug = `a-${slug}`;
    return slug;
  }

  async function generateWorkspace(assignee) {
    const name = (assignee || "").trim();
    if (!name) { toast("Enter an assignee name first", true); return; }
    try {
      const data = await api(`/api/runs/${state.runId}/workspace`, {
        method: "POST",
        body: JSON.stringify({ role: state.role, assignee: name }),
      });
      state.workspace = { assignee: name, data };
      state.workspaceAssignee = name;
      localStorage.setItem("s7cc.workspaceAssignee", name);
      render();
      toast(`Workspace generated for ${name}`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function loadWorkspace(assignee) {
    const name = (assignee || "").trim();
    if (!name) { toast("Enter an assignee name first", true); return; }
    try {
      const data = await api(`/api/runs/${state.runId}/workspace/${encodeURIComponent(name)}`);
      state.workspace = { assignee: name, data };
      state.workspaceAssignee = name;
      localStorage.setItem("s7cc.workspaceAssignee", name);
      render();
    } catch {
      toast(`No saved workspace yet for ${name} — generate one first`, true);
    }
  }

  function renderWorkspace() {
    const d = state.data;
    const stories = d.planning?.stories ?? [];
    const tasks = d.build?.tasks ?? [];
    const people = [...new Set(
      [...stories.map((s) => s.owner), ...tasks.map((t) => t.owner)].filter(Boolean)
    )].sort();

    const parts = [sectionTitle(
      "My Workspace",
      "Package one person's assigned stories, tasks and design context into a single handoff file — the artifact-plane handoff CLAUDE.md calls for at the app/CLI boundary",
    )];

    const nameInput = el("input", {
      type: "text", list: "assigneeList", placeholder: "e.g. A. Ng",
      value: state.workspaceAssignee || "",
    });
    const datalist = el("datalist", { id: "assigneeList" }, people.map((p) => el("option", { value: p })));

    parts.push(el("div", { class: "card" },
      el("label", { class: "fld", text: "Assignee" }), nameInput, datalist,
      el("div", { class: "actions-row" },
        el("button", { class: "primary", text: "Generate workspace",
          onclick: () => generateWorkspace(nameInput.value) }),
        el("button", { class: "ghost", text: "Load saved workspace",
          onclick: () => loadWorkspace(nameInput.value) }),
      ),
    ));

    if (people.length) {
      parts.push(el("div", { class: "card" },
        el("h3", { text: "Currently assigned" }),
        el("ul", { class: "plain" }, people.map((p) =>
          el("li", {},
            el("a", {
              href: "#", text: p,
              onclick: (e) => { e.preventDefault(); nameInput.value = p; loadWorkspace(p); },
            }))),
        ),
      ));
    } else {
      parts.push(el("div", { class: "card" },
        el("p", { class: "hint", text:
          "No stories or tasks carry an owner yet. Set one from Planning → " +
          "Story routing, or from a task's detail view in Build & Review, " +
          "then come back here to generate their workspace." })));
    }

    const ws = state.workspace;
    if (ws && ws.data) {
      const wd = ws.data;
      parts.push(sectionTitle(`Workspace — ${wd.assignee}`,
        `${wd.stories.length} ${wd.stories.length === 1 ? "story" : "stories"} · ${wd.tasks.length} tasks`));
      parts.push(el("div", { class: "card" },
        el("div", { class: "kv" },
          el("b", { text: "Workspace id" }), el("span", { class: "mono", text: wd.workspace_id }),
          el("b", { text: "Generated" }), el("span", { class: "mono", text: wd.generated_at }),
          el("b", { text: "Version" }), el("span", { text: `v${wd.version}` }),
          el("b", { text: "Provenance" }), el("span", {}, prov(wd.provenance)),
          el("b", { text: "Files" }),
          el("code", { text: `artifacts/runs/${state.runId}/workspaces/${jsSlug(wd.assignee)}/workspace.json · workspace.md` }),
        ),
        el("div", { class: "actions-row" },
          el("a", {
            class: "ghost", href: `/api/runs/${state.runId}/workspace/${encodeURIComponent(wd.assignee)}/markdown`,
            target: "_blank", text: "Download handoff (.md)",
          })),
      ));

      if (wd.blocked?.length) {
        parts.push(el("div", { class: "card warn" },
          el("h3", { text: "Blocked" }),
          el("ul", { class: "plain" }, wd.blocked.map((b) => el("li", { text: b }))),
        ));
      }

      parts.push(sectionTitle("Stories in this workspace"));
      if (!wd.stories.length) {
        parts.push(el("div", { class: "card" }, el("p", { text: "No stories are currently assigned to this person." })));
      } else {
        parts.push(el("div", { class: "table-wrap" },
          el("table", {},
            el("thead", {}, el("tr", {},
              ["Story", "Title", "Status", "Sprint", "Est", "Depends on"].map((h) => el("th", { text: h })))),
            el("tbody", {}, wd.stories.map((s) =>
              el("tr", {},
                el("td", { class: "mono", text: s.story_id }),
                el("td", { text: s.title }),
                el("td", {}, badge(s.status)),
                el("td", { text: `S${s.sprint}` }),
                el("td", { text: `${s.estimate} pts` }),
                el("td", { class: "mono", text: (s.dependencies ?? []).join(", ") || "—" }),
              ))),
          ),
        ));
      }

      parts.push(sectionTitle("Tasks in this workspace"));
      parts.push(!wd.tasks.length
        ? el("div", { class: "card" }, el("p", { text: "No tasks are currently assigned to this person." }))
        : workQueueTable(wd.tasks));

      if (wd.design_rules && Object.keys(wd.design_rules).length) {
        parts.push(el("div", { class: "card" },
          el("h3", { text: "Design context" }),
          el("ul", { class: "plain" }, Object.entries(wd.design_rules).map(([k, v]) =>
            el("li", {}, el("b", { text: `${k}: ` }), v))),
        ));
      }
    }

    return el("section", {}, parts);
  }

  function renderBuildReview() {
    const d = state.data;
    const tasks = d.build?.tasks ?? [];
    const reviews = d.build?.reviews ?? [];
    const parts = [sectionTitle("Stage 3 — Build & Independent Review",
      "Test-first development; no phase self-approves")];

    if (!tasks.length) {
      parts.push(el("div", { class: "card" },
        el("p", { text: "The work queue is seeded when the plan is signed at Gate 1." })));
      return el("section", {}, parts);
    }

    parts.push(workQueueTable(tasks, (id) => { state.taskId = id; render(); }));

    const task = tasks.find((t) => t.task_id === state.taskId) ?? tasks.find((t) => t.status !== "completed") ?? tasks[0];
    const taskReviews = reviews.filter((r) => r.task_id === task.task_id);
    const latestReview = taskReviews[taskReviews.length - 1];

    // customer-safe development view (spec §9C)
    parts.push(sectionTitle(`${task.task_id} — ${task.summary}`, `Accountable: ${task.accountable_team}`));
    parts.push(el("div", { class: "grid cols-2" },
      el("div", { class: "card" },
        el("h3", { text: "Development view" }),
        el("div", { class: "kv", style: "margin-top:8px" },
          el("b", { text: "Status" }), el("span", {}, badge(task.status)),
          el("b", { text: "Progress" }), el("span", { text: `${task.progress_pct}%` }),
          el("b", { text: "Owner" }), el("span", { text: task.owner || "unassigned" }),
          el("b", { text: "Current activity" }), el("span", { text: task.current_activity || "—" }),
          el("b", { text: "Files changed" }), el("span", { text: String(task.files_changed) }),
          el("b", { text: "Lines" }), el("span", { text: `+${task.lines_added} / −${task.lines_removed}` }),
          el("b", { text: "Coverage" }), el("span", { text: task.coverage_pct ? `${task.coverage_pct}%` : "—" }),
          el("b", { text: "Change summary" }), el("span", { text: task.change_summary || "—" }),
          el("b", { text: "Evidence" }), el("span", {}, prov(task.provenance)),
        ),
        task.changed_files?.length ? el("details", { style: "margin-top:10px" },
          el("summary", { text: "Technical evidence (sanitised)" }),
          el("div", { class: "kv", style: "margin-top:8px" },
            el("b", { text: "Changed files" }),
            el("span", {}, el("ul", { class: "plain" }, task.changed_files.map((f) => el("li", {}, el("code", { text: f }))))),
            el("b", { text: "Commit" }), el("code", { text: task.commit_ref || "—" }),
            el("b", { text: "Pull request" }), el("code", { text: task.pr_ref || "—" }),
            el("b", { text: "Version" }), el("span", { text: `v${task.version}` }),
          )) : null,
        el("div", { class: "actions-row" },
          (() => {
            const assignInput = el("input", { type: "text", placeholder: "Assign to (name)", value: task.owner || "" });
            return el("span", { style: "display:flex;gap:8px;align-items:center" },
              assignInput,
              el("button", { class: "ghost", text: "Assign",
                onclick: () => act(`/tasks/${task.task_id}/assign`, { owner: assignInput.value }, `${task.task_id} assigned`) }),
            );
          })(),
        ),
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Run to review",
            title: "start → red tests → develop → verify → submit, each step logged",
            onclick: () => act(`/tasks/${task.task_id}/run-to-review`, {}, `${task.task_id} submitted for review`) }),
          el("button", { class: "ghost", text: "Start", onclick: () => act(`/tasks/${task.task_id}/start`, {}, "Task started") }),
          el("button", { class: "ghost", text: "Generate tests", onclick: () => act(`/tasks/${task.task_id}/generate-tests`, {}, "Red baseline recorded") }),
          el("button", { class: "ghost", text: "Develop", onclick: () => act(`/tasks/${task.task_id}/develop`, {}, "Change implemented") }),
          el("button", { class: "ghost", text: "Verify", onclick: () => act(`/tasks/${task.task_id}/verify`, {}, "Developer verification done") }),
          el("button", { class: "ghost", text: "Submit for review", onclick: () => act(`/tasks/${task.task_id}/submit-review`, {}, "Submitted") }),
        ),
      ),
      el("div", { class: `card ${latestReview ? (latestReview.result === "passed" ? "ok" : "bad") : ""}` },
        el("div", { class: "section-title" },
          el("h3", { text: "Independent review" }),
          latestReview ? badge(latestReview.result === "passed" ? "passed" : "blocked") : null),
        el("p", { class: "hint", text: "The reviewer is isolated from development: it receives the signed plan, story, acceptance criteria, change summary and test evidence — and verifies against the criteria, not the tests." }),
        latestReview ? el("div", { class: "kv", style: "margin-top:8px" },
          el("b", { text: "Review" }), el("span", { class: "mono", text: `${latestReview.review_id} (v${latestReview.version})` }),
          el("b", { text: "Reviewer" }), el("span", { text: latestReview.reviewer }),
          el("b", { text: "Critical gaps" }), el("span", { text: String(latestReview.critical_gaps) }),
          el("b", { text: "Major gaps" }), el("span", { text: String(latestReview.major_gaps) }),
          el("b", { text: "Minor gaps" }), el("span", { text: String(latestReview.minor_gaps) }),
        ) : el("p", { text: "No review yet for this task." }),
        latestReview?.findings?.length ? el("div", { style: "margin-top:8px" },
          latestReview.findings.map((f) => el("div", { class: "card bad", style: "margin-top:8px" },
            el("h3", { text: `${f.finding_id} · ${f.severity.toUpperCase()} · ${f.ac_id}` }),
            el("p", { text: f.summary }),
            el("p", { class: "hint", text: f.detail })))) : null,
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Execute review",
            onclick: () => act(`/reviews/${task.task_id}/execute`, {}, "Review executed") }),
          el("button", { class: "ghost", text: "Return to development",
            onclick: () => act(`/reviews/${task.task_id}/return-to-development`, {}, "Returned to development") }),
        ),
      ),
    ));

    // test-first evidence (spec §9D)
    if (task.tests?.length) {
      parts.push(sectionTitle("Test-first evidence",
        "Every acceptance criterion has a test that failed before implementation"));
      parts.push(el("div", { class: "table-wrap" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["Test", "Name", "Criterion", "Initial", "Current"].map((h) => el("th", { text: h })))),
          el("tbody", {}, task.tests.map((t) => el("tr", {},
            el("td", { class: "mono", text: t.test_id }),
            el("td", { class: "mono", text: t.name }),
            el("td", { class: "mono", text: t.ac_id }),
            el("td", {}, badge(t.initial_result)),
            el("td", {}, badge(t.current_result)),
          ))),
        ),
      ));
    }

    const gate = (d.gates ?? []).find((g) => g.gate_id === "G2");
    parts.push(el("div", { class: `card ${gate?.status === "passed" ? "ok" : "highlight"}`, style: "margin-top:14px" },
      el("div", { class: "section-title" },
        el("h3", { text: "Gate 2 — Independent review" }), badge(gate?.status ?? "not_started")),
      (gate?.conditions ?? []).length
        ? el("ul", { class: "plain" }, gate.conditions.map((c) =>
          el("li", {}, `${c.met ? "✓" : "✗"} ${c.condition}`,
            c.detail ? el("span", { class: "hint", text: ` — ${c.detail}` }) : null)))
        : el("p", { class: "hint", text: "Conditions evaluate as reviews execute. NO PHASE SELF-APPROVES." }),
    ));

    return el("section", {}, parts);
  }

  function storyGaps(s) {
    const gaps = [];
    if (!s.purpose) gaps.push("purpose missing");
    if (!s.acceptance_criteria?.length) gaps.push("no acceptance criteria");
    if (!s.accountable_team) gaps.push("no accountable team");
    if (!s.target_component) gaps.push("no target component");
    if (!s.rollback_plan) gaps.push("no rollback plan");
    if (!s.task_type) gaps.push("no task type");
    return gaps;
  }

  function renderStories() {
    const stories = state.data.planning?.stories ?? [];
    if (stories.length === 0) return notBuilt("Epics & Stories", "the Planning stage — generate the draft plan first");
    return el("section", {},
      sectionTitle("Epics & Stories", "EPIC-S7-001 decomposition — demonstration data"),
      el("div", { class: "grid cols-2" }, stories.map((s) =>
        el("div", { class: "card" },
          el("div", { class: "section-title" },
            el("h3", {}, el("span", { class: "mono", text: s.story_id + " " }), s.title),
            prov(s.provenance)),
          el("p", { class: "hint", text: s.purpose }),
          el("div", { class: "kv", style: "margin-top:10px" },
            el("b", { text: "Team" }), el("span", { text: s.accountable_team + (s.contributing_teams.length ? ` (+ ${s.contributing_teams.join(", ")})` : "") }),
            el("b", { text: "Component" }), el("span", { text: s.target_component }),
            el("b", { text: "Repository" }), el("code", { text: s.target_repository }),
            el("b", { text: "Feature flag" }), el("span", {}, s.feature_flag ? el("code", { text: s.feature_flag.name }) : "—"),
            el("b", { text: "Rollback" }), el("span", { text: s.rollback_plan?.method ?? "—" }),
            el("b", { text: "Version" }), el("span", { text: `v${s.version}` }),
          ),
          el("h3", { style: "margin-top:12px", text: "Acceptance criteria" }),
          el("ul", { class: "plain" }, s.acceptance_criteria.map((ac) =>
            el("li", {}, el("span", { class: "mono", text: ac.ac_id + " " }), ac.text)),
          ),
        ))),
    );
  }

  function gatePanel(gateId, title, hint) {
    const gate = (state.data.gates ?? []).find((g) => g.gate_id === gateId);
    return el("div", { class: `card ${gate?.status === "passed" ? "ok" : "highlight"}`, style: "margin-top:14px" },
      el("div", { class: "section-title" }, el("h3", { text: title }), badge(gate?.status ?? "not_started")),
      (gate?.conditions ?? []).length
        ? el("ul", { class: "plain" }, gate.conditions.map((c) =>
          el("li", {}, `${c.met ? "✓" : "✗"} ${c.condition}`,
            c.detail ? el("span", { class: "hint", text: ` — ${c.detail}` }) : null)))
        : el("p", { class: "hint", text: hint }),
      gate?.decided_by ? el("p", { class: "hint", text: `Decided by ${gate.decided_by} at ${gate.decided_at}` }) : null,
    );
  }

  function renderQuality() {
    const d = state.data;
    const report = d.quality;
    const parts = [sectionTitle("Stage 4 — Quality",
      "Evidence aggregated across every story. The gate is explicit conditions, never the score.")];

    if (!report) {
      parts.push(el("div", { class: "card" },
        el("p", { text: "Quality aggregation opens once the independent-review gate (G2) has passed for every task." }),
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Run quality checks",
            onclick: () => act("/quality/run", {}, "Quality checks aggregated") })),
      ));
      return el("section", {}, parts);
    }

    const checks = report.checks ?? [];
    const passed = checks.filter((c) => c.status === "passed").length;
    parts.push(el("div", { class: "grid cols-4" },
      el("div", { class: "card metric" }, el("div", { class: "v", text: `${passed}/${checks.filter((c) => c.status !== "not_applicable").length}` }), el("div", { class: "l", text: "Checks passed" })),
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(report.risks?.length ?? 0) }), el("div", { class: "l", text: "Open risks" })),
      el("div", { class: "card metric" }, el("div", { class: "v", text: String(report.exceptions?.length ?? 0) }), el("div", { class: "l", text: "Approved exceptions" })),
      el("div", { class: "card metric" },
        el("div", { class: "v", text: `${report.quality_score}` }),
        el("div", { class: "l", text: "Score (informational)" })),
    ));
    parts.push(el("p", { class: "hint", style: "margin-top:6px", text: report.score_note }));

    parts.push(sectionTitle("Quality evidence"));
    parts.push(el("div", { class: "table-wrap" },
      el("table", {},
        el("thead", {}, el("tr", {}, ["Check", "Name", "Status", "Evidence", "Owner"].map((h) => el("th", { text: h })))),
        el("tbody", {}, checks.map((c) => el("tr", {},
          el("td", { class: "mono", text: c.check_id }),
          el("td", { text: c.name }),
          el("td", {}, badge(c.status === "not_applicable" ? "not_started" : c.status)),
          el("td", { text: c.evidence || "—" }),
          el("td", { text: c.owner }),
        ))),
      ),
    ));

    parts.push(el("div", { class: "grid cols-2", style: "margin-top:14px" },
      el("div", { class: "card warn" },
        el("h3", { text: "Risks" }),
        el("ul", { class: "plain" }, (report.risks ?? []).map((r) =>
          el("li", {}, el("b", { text: `${r.risk_id} (${r.severity}): ` }), r.description))),
      ),
      el("div", { class: "card" },
        el("h3", { text: "Approved exceptions" }),
        el("ul", { class: "plain" }, (report.exceptions ?? []).map((x) =>
          el("li", {}, el("b", { text: `${x.exception_id}: ` }), x.description,
            el("span", { class: "hint", text: ` — approved by ${x.approved_by}` })))),
      ),
    ));

    parts.push(el("div", { class: "card", style: "margin-top:14px" },
      el("h3", { text: "Release recommendation" }),
      el("p", { text: report.recommendation }),
      el("div", { class: "actions-row" },
        el("button", { class: "ghost", text: "Re-run checks", onclick: () => act("/quality/run", {}, "Quality checks re-aggregated") }),
        el("button", { class: "primary approve", text: "Decide quality gate (QA Lead)",
          onclick: () => act("/quality/decide", {}, "Quality gate decided") })),
    ));
    parts.push(gatePanel("G3", "Gate 3 — Quality",
      "Conditions evaluate when the QA Lead decides the gate."));
    return el("section", {}, parts);
  }

  function renderRelease() {
    const d = state.data;
    const rec = d.release;
    const parts = [sectionTitle("Stage 5 — Release",
      "A genuine blocking human gate: named approvals, then deployment, then handover")];

    if (!rec) {
      parts.push(el("div", { class: "card" },
        el("p", { text: "Release opens after the quality gate (G3) passes." }),
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "Request release approval",
            onclick: () => act("/release/request-approval", {}, "Release approval requested") })),
      ));
      return el("section", {}, parts);
    }

    parts.push(el("div", { class: "grid cols-2" },
      el("div", { class: "card highlight" },
        el("h3", { text: "Release summary" }),
        el("div", { class: "kv", style: "margin-top:8px" },
          el("b", { text: "Release" }), el("span", { class: "mono", text: rec.release_id }),
          el("b", { text: "Epic" }), el("span", { class: "mono", text: rec.epic_id }),
          el("b", { text: "Version" }), el("span", { text: rec.version }),
          el("b", { text: "Environment" }), el("span", { text: rec.environment }),
          el("b", { text: "Window" }), el("span", { text: rec.release_window }),
          el("b", { text: "Feature flag" }), el("code", { text: rec.feature_flag }),
          el("b", { text: "Rollback" }), el("span", { text: rec.rollback_plan }),
          el("b", { text: "Status" }), el("span", {}, badge(rec.status)),
        ),
      ),
      el("div", { class: "card" },
        el("h3", { text: "Required approvals" }),
        el("p", { class: "hint", text: "Business Owner, Engineering Lead, QA Lead and Release Manager must each approve under their own role. Switch the acting role in the header to record each one." }),
        renderApprovalMatrix(),
        renderApprovalForm(),
      ),
    ));

    if (rec.deployment) {
      const dep = rec.deployment;
      parts.push(el("div", { class: "card ok", style: "margin-top:14px" },
        el("div", { class: "section-title" }, el("h3", { text: "Deployment" }), badge(dep.status)),
        el("div", { class: "kv", style: "margin-top:8px" },
          el("b", { text: "Deployment" }), el("span", { class: "mono", text: dep.deployment_id }),
          el("b", { text: "Pipeline" }), el("span", { text: dep.pipeline_ref }),
          el("b", { text: "Strategy" }), el("span", { text: dep.strategy }),
          el("b", { text: "Artifacts" }), el("span", { text: String(dep.artifact_count) }),
          el("b", { text: "Smoke tests" }), el("span", { text: dep.smoke_test_status }),
          el("b", { text: "Post-deployment" }),
          el("span", {}, el("ul", { class: "plain" }, dep.post_checks.map((p) => el("li", { text: p })))),
          el("b", { text: "Deployed at" }), el("span", { class: "mono", text: dep.deployed_at }),
        ),
      ));
    }

    if (rec.handover) {
      const h = rec.handover;
      parts.push(el("div", { class: "card ok", style: "margin-top:14px" },
        el("h3", { text: "Support handover" }),
        el("div", { class: "kv", style: "margin-top:8px" },
          el("b", { text: "Support team" }), el("span", { text: h.support_team }),
          el("b", { text: "Runbook" }), el("code", { text: h.runbook_ref }),
          el("b", { text: "Knowledge article" }), el("span", { text: h.knowledge_article_ref }),
          el("b", { text: "Monitoring alerts" }),
          el("span", {}, el("ul", { class: "plain" }, h.monitoring_alerts.map((a) => el("li", { text: a })))),
          el("b", { text: "Escalation" }), el("span", { text: h.escalation_path }),
          el("b", { text: "Known limitations" }),
          el("span", {}, el("ul", { class: "plain" }, h.known_limitations.map((a) => el("li", { text: a })))),
          el("b", { text: "Hypercare" }), el("span", { text: `${h.hypercare_days} days` }),
          el("b", { text: "Accepted by" }), el("span", { text: `${h.accepted_by} at ${h.accepted_at}` }),
        ),
      ));
    }

    parts.push(el("div", { class: "actions-row", style: "margin-top:14px" },
      el("button", { class: "primary", text: "Deploy to production (Release Manager)",
        onclick: () => act("/release/deploy", {}, "Deployment complete") }),
      el("button", { class: "primary approve", text: "Complete support handover",
        onclick: () => act("/release/handover", {}, "Handover accepted — run complete") }),
    ));
    parts.push(gatePanel("G4", "Gate 4 — Release",
      "Conditions evaluate at deployment: all gates green, all approvals present, nothing stale."));
    return el("section", {}, parts);
  }

  function renderApprovalMatrix() {
    const releaseApprovals = (state.data.approvals ?? []).filter((a) => a.subject === "release");
    const required = ["business_owner", "engineering_lead", "qa_lead", "release_manager"];
    return el("ul", { class: "plain" }, required.map((r) => {
      const got = releaseApprovals.filter((a) => a.role === r).pop();
      return el("li", {},
        el("b", { text: r.replaceAll("_", " ") + ": " }),
        got ? el("span", {}, badge(got.decision === "approved" ? "passed" : "failed"),
          ` ${got.approver} — ${got.decided_at}`) : badge("waiting_for_approval"));
    }));
  }

  function renderApprovalForm() {
    const name = el("input", { type: "text", placeholder: "Approver name (required)" });
    const note = el("input", { type: "text", placeholder: "Note (optional)" });
    return el("div", { style: "margin-top:10px" },
      el("label", { class: "fld", text: "Approver" }), name,
      el("label", { class: "fld", text: "Note" }), note,
      el("div", { class: "actions-row" },
        el("button", { class: "primary approve", text: "Approve as current role",
          onclick: () => act("/release/approve", { approver: name.value, note: note.value, decision: "approved" }, "Approval recorded") }),
        el("button", { class: "ghost danger-ghost", text: "Reject release",
          onclick: () => act("/release/approve", { approver: name.value, note: note.value, decision: "rejected" }, "Rejection recorded") }),
      ),
    );
  }

  function renderRisks() {
    const report = state.data.quality;
    const risks = report?.risks ?? [];
    const stale = state.data.staleness ?? [];
    const amendments = state.data.amendments ?? [];
    const design = state.data.design;
    const parts = [sectionTitle("Risks & Alerts",
      "Staleness is detected from upstream pointers and hashes in the provenance ledger")];

    if (risks.length === 0 && stale.length === 0 && amendments.length === 0) {
      parts.push(el("div", { class: "card" },
        el("p", { text: "No open risks, staleness alerts or amendments in this run yet." })));
    }

    if (stale.length) {
      parts.push(el("div", { class: "card bad" },
        el("h3", { text: `Release gate blocked — ${stale.length} stale artifact(s)` }),
        el("p", { class: "hint", text: "An upstream artifact changed after these were produced. Each must be re-validated as a new version before release; nothing is silently updated." })));
      parts.push(el("div", { class: "table-wrap", style: "margin-top:10px" },
        el("table", {},
          el("thead", {}, el("tr", {}, ["Artifact", "Type", "Version", "Status", "Reason"].map((h) => el("th", { text: h })))),
          el("tbody", {}, stale.map((s) => el("tr", {},
            el("td", { class: "mono", text: s.artifact_id }),
            el("td", { text: s.artifact_type }),
            el("td", { text: `v${s.version}` }),
            el("td", {}, badge("stale")),
            el("td", { text: s.reason }),
          ))))));
    }

    risks.forEach((r) => parts.push(el("div", { class: "card warn", style: "margin-top:10px" },
      el("h3", { text: `${r.risk_id} — ${r.severity}` }), el("p", { text: r.description }))));

    if (amendments.length) {
      parts.push(sectionTitle("Amendments", "Controlled change management — append-only"));
      const seen = new Set();
      [...amendments].reverse().forEach((a) => {
        if (seen.has(a.amendment_id)) return;
        seen.add(a.amendment_id);
        parts.push(el("div", { class: `card ${a.implementation_status === "completed" ? "ok" : "warn"}` },
          el("div", { class: "section-title" },
            el("h3", { text: `${a.amendment_id} — ${a.reason}` }),
            badge(a.implementation_status === "completed" ? "completed" : "in_progress")),
          el("div", { class: "kv", style: "margin-top:8px" },
            el("b", { text: "Initiator" }), el("span", { text: a.initiator }),
            el("b", { text: "Impact" }), el("span", { text: a.impact_assessment }),
            el("b", { text: "Affected" }), el("span", { class: "mono", text: (a.affected_artifacts ?? []).join(", ") || "—" }),
            el("b", { text: "Required changes" }),
            el("span", {}, el("ul", { class: "plain" }, (a.required_changes ?? []).map((c) => el("li", { text: c })))),
            el("b", { text: "Verification" }), el("span", {}, badge(a.verification_status === "completed" ? "passed" : a.verification_status)),
          )));
      });
    }

    parts.push(el("div", { class: "card", style: "margin-top:14px" },
      el("h3", { text: "Demonstration controls" }),
      el("p", { class: "hint", text: design?.version > 1
        ? "Upstream change applied: DES-001 is at v2 (SME ruling on draft retention)."
        : "Simulate the SME ruling that changes DES-001 after downstream work exists — downstream artifacts go stale and release blocks." }),
      el("div", { class: "actions-row" },
        el("button", { class: "primary", text: "Apply upstream SME ruling",
          onclick: () => act("/change/upstream", {}, "DES-001 amended — downstream marked stale") }),
        el("button", { class: "primary approve", text: "Run self-correction workflow",
          onclick: () => act("/change/self-correct", {}, "Self-correction complete") }),
      )));
    return el("section", {}, parts);
  }

  function renderTraceability() {
    const rows = state.data.traceability ?? [];
    if (!rows.length) return notBuilt("Traceability", "the Planning stage — the chain builds as artifacts exist");
    const sel = state.traceSel;
    const selected = rows.find((r) => r.ac === sel);
    return el("section", {},
      sectionTitle("Traceability matrix",
        "Requirement → design → story → criterion → task → change → test → review → quality → deployment → handover"),
      selected ? el("div", { class: "card highlight", style: "margin-bottom:14px" },
        el("h3", { text: `Chain for ${selected.ac}` }),
        el("p", { class: "mono", style: "margin-top:8px", text: [
          selected.requirement, selected.design, selected.story, selected.ac,
          selected.task, selected.pr, ...(selected.tests ?? []), selected.review,
          selected.quality, selected.deployment, selected.handover,
        ].filter(Boolean).join(" → ") })) : null,
      el("div", { class: "table-wrap" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["Story", "Criterion", "Task", "Change", "Tests", "Review", "Quality", "Deploy", "Handover"].map((h) => el("th", { text: h })))),
          el("tbody", {}, rows.map((r) => el("tr", { style: "cursor:pointer", onclick: () => { state.traceSel = r.ac; render(); } },
            el("td", { class: "mono", text: r.story }),
            el("td", { class: "mono", text: r.ac }),
            el("td", { class: "mono", text: r.task ?? "—" }),
            el("td", { class: "mono", text: r.pr ?? "—" }),
            el("td", { class: "mono", text: (r.tests ?? []).join(", ") || "—" }),
            el("td", {}, r.review ? el("span", {}, el("span", { class: "mono", text: r.review + " " }),
              badge(r.review_result === "passed" ? "passed" : "blocked")) : "—"),
            el("td", { class: "mono", text: r.quality ?? "—" }),
            el("td", { class: "mono", text: r.deployment ?? "—" }),
            el("td", { class: "mono", text: r.handover ?? "—" }),
          ))),
        ),
      ),
    );
  }

  function renderArtifacts() {
    const rows = state.data.provenance ?? [];
    return el("section", {},
      sectionTitle("Artifacts", "Current version of every artifact this run has produced"),
      el("div", { class: "table-wrap" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["Artifact", "Type", "Version", "Author", "Created", "Status"].map((h) => el("th", { text: h })))),
          el("tbody", {},
            rows.map((r) => el("tr", {},
              el("td", { class: "mono", text: r.artifact_id }),
              el("td", { text: r.artifact_type }),
              el("td", { text: `v${r.version}` }),
              el("td", { text: r.author }),
              el("td", { class: "mono", text: r.timestamp }),
              el("td", {}, r.stale ? badge("stale") : badge("completed")),
            ))),
        ),
      ),
    );
  }

  function renderProvenance() {
    const rows = state.data.provenance_ledger ?? [];
    return el("section", {},
      sectionTitle("Provenance ledger", "Append-only. Every artifact version, hashed. History is never rewritten."),
      el("div", { class: "table-wrap" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["Event", "Artifact", "Type", "v", "SHA-256", "Author", "Stage", "Action", "Outcome", "Inputs"].map((h) => el("th", { text: h })))),
          el("tbody", {},
            rows.map((r) => el("tr", {},
              el("td", { class: "mono", text: r.event_id }),
              el("td", { class: "mono", text: r.artifact_id }),
              el("td", { text: r.artifact_type }),
              el("td", { text: String(r.version) }),
              el("td", { class: "mono", title: r.sha256, text: r.sha256.slice(0, 10) + "…" }),
              el("td", { text: r.author }),
              el("td", { text: r.stage }),
              el("td", { text: r.action }),
              el("td", { text: r.outcome }),
              el("td", { class: "mono", text: (r.inputs ?? []).join(", ") || "—" }),
            ))),
        ),
      ),
    );
  }

  function renderActivity() {
    const rows = [...(state.data.activity ?? [])].reverse();
    const s = state.data.activity_summary ?? {};
    return el("section", {},
      sectionTitle("Factory activity log", "Every workflow, gate event and human decision"),
      el("div", { class: "grid cols-3" },
        Object.entries(s.counters ?? {}).map(([k, v]) =>
          el("div", { class: "card metric" },
            el("div", { class: "v", text: String(v) }),
            el("div", { class: "l", text: k.replaceAll("_", " ") }))),
      ),
      el("div", { class: "table-wrap", style: "margin-top:14px" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["Time", "Stage", "Actor", "Type", "Workflow", "Outcome", "Details"].map((h) => el("th", { text: h })))),
          el("tbody", {},
            rows.map((r) => el("tr", {},
              el("td", { class: "mono", text: r.timestamp }),
              el("td", { text: r.stage }),
              el("td", { text: r.actor }),
              el("td", { text: r.actor_type }),
              el("td", { text: r.workflow || "—" }),
              el("td", { text: r.outcome || "—" }),
              el("td", { text: r.details || "—" }),
            ))),
        ),
      ),
    );
  }

  function renderApprovals() {
    const rows = state.data.approvals ?? [];
    return el("section", {},
      sectionTitle("Approvals", "Append-only record of every human decision"),
      rows.length === 0
        ? el("div", { class: "card" }, el("p", { text: "No approvals recorded yet in this run." }))
        : el("div", { class: "table-wrap" },
          el("table", {},
            el("thead", {}, el("tr", {},
              ["Id", "Subject", "Role", "Approver", "Decision", "Note", "When"].map((h) => el("th", { text: h })))),
            el("tbody", {},
              rows.map((r) => el("tr", {},
                el("td", { class: "mono", text: r.approval_id }),
                el("td", { text: r.subject }),
                el("td", { text: r.role }),
                el("td", { text: r.approver }),
                el("td", {}, badge(r.decision === "approved" ? "passed" : "failed")),
                el("td", { text: r.note || "—" }),
                el("td", { class: "mono", text: r.decided_at }),
              ))),
          ),
        ),
    );
  }

  function renderReports() {
    const s = state.data.activity_summary ?? {};
    const run = state.data.run;
    const stageTime = s.stage_time_s ?? {};
    const total = Object.values(stageTime).reduce((a, b) => a + b, 0);
    const stageLabel = (k) => (STAGES.find(([key]) => key === k)?.[1]) ?? k;
    return el("section", {},
      sectionTitle("Reports", "Computed from the activity ledger — durations are simulated workflow durations"),
      el("div", { class: "grid cols-4" },
        el("div", { class: "card metric" }, el("div", { class: "v", text: `${Math.round(total)}s` }), el("div", { class: "l", text: "Total workflow time" })),
        el("div", { class: "card metric" }, el("div", { class: "v", text: String(s.counters?.ai_workflows ?? 0) }), el("div", { class: "l", text: "Automated workflows" })),
        el("div", { class: "card metric" }, el("div", { class: "v", text: String(s.counters?.human_approvals ?? 0) }), el("div", { class: "l", text: "Human decisions" })),
        el("div", { class: "card metric" }, el("div", { class: "v", text: run.status.replaceAll("_", " ") }), el("div", { class: "l", text: "Run outcome" })),
      ),
      sectionTitle("Bottleneck insights", "Where workflow time accrued, by stage"),
      el("div", { class: "card" },
        el("ul", { class: "plain" },
          Object.entries(stageTime).map(([k, v]) => el("li", {},
            el("b", { text: stageLabel(k) + ": " }),
            `${Math.round(v)}s`,
            el("span", { class: "hint", text: total ? ` — ${Math.round((100 * v) / total)}%` : "" }))))),
      sectionTitle("Ledger counters"),
      el("div", { class: "grid cols-3" },
        Object.entries(s.counters ?? {}).map(([k, v]) =>
          el("div", { class: "card metric" },
            el("div", { class: "v", text: String(v) }),
            el("div", { class: "l", text: k.replaceAll("_", " ") })))),
    );
  }

  const DEMO_SCENARIOS = [
    ["happy-path", "Happy path — full successful run to handover"],
    ["review-failure", "Independent review failure — US-003 blocked"],
    ["missing-test-coverage", "Missing test coverage — quality gate blocks"],
    ["staleness", "Upstream change — downstream stale, release blocked"],
    ["release-rejected", "Release approval rejected by Business Owner"],
  ];

  function renderSettings() {
    const run = state.data.run;
    return el("section", {},
      sectionTitle("Settings"),
      el("div", { class: "card" },
        el("div", { class: "kv" },
          el("b", { text: "Run id" }), el("span", { class: "mono", text: run.run_id }),
          el("b", { text: "Demo mode" }), el("span", { text: run.mode }),
          el("b", { text: "Acting role" }), el("span", { text: state.role.replaceAll("_", " ") }),
          el("b", { text: "State storage" }), el("code", { text: `artifacts/runs/${run.run_id}/` }),
        ),
        el("div", { class: "actions-row" },
          el("button", { class: "primary", text: "New run", onclick: newRun }),
          el("button", { class: "ghost danger-ghost", text: "Reset this run", onclick: resetRun }),
        ),
      ),
      sectionTitle("Load demo scenario", "Each creates a fresh run driven to a known state through the real engine — gates, roles and ledgers all execute"),
      el("div", { class: "grid cols-2" },
        DEMO_SCENARIOS.map(([key, label]) =>
          el("div", { class: "card" },
            el("h3", { text: label }),
            el("div", { class: "actions-row" },
              el("button", { class: "primary", text: "Load", onclick: () => loadDemo(key) })))),
      ),
    );
  }

  async function loadDemo(action) {
    try {
      const created = await api(`/api/demo/${action}`, { method: "POST", body: "{}" });
      state.runId = created.run.run_id;
      localStorage.setItem("s7cc.runId", state.runId);
      state.data = created;
      state.section = "overview";
      render();
      toast(`Scenario '${action}' loaded as ${state.runId}`);
    } catch (err) { toast(err.message, true); }
  }

  async function newRun() {
    try {
      const created = await api("/api/runs", { method: "POST", body: JSON.stringify({ mode: "simulation" }) });
      state.runId = created.run.run_id;
      localStorage.setItem("s7cc.runId", state.runId);
      state.data = created;
      render();
      toast(`Run ${state.runId} created`);
    } catch (err) { toast(err.message, true); }
  }

  async function resetRun() {
    await act("/reset", {}, "Run reset to seeded state");
  }

  // --- render --------------------------------------------------------------

  function render() {
    if (!state.data) return;
    renderChrome();
    const renderer = RENDERERS[state.section] ?? renderOverview;
    main.replaceChildren(renderer());
  }

  // --- boot ----------------------------------------------------------------

  $("refreshBtn").addEventListener("click", refresh);
  $("resetBtn").addEventListener("click", resetRun);

  (async () => {
    try {
      state.roles = await api("/api/roles");
    } catch { state.roles = []; }
    await refresh();
  })();
})();
