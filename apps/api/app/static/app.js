/* Gatewise decision index.
   Fetches only what the API actually recorded. An empty database renders
   "No evaluations yet" rather than placeholder metrics. */

const RISK_LABELS = ["trivial", "low", "moderate", "high", "critical"];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

async function get(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(path + " -> HTTP " + response.status);
  return response.json();
}

function bar(percent, tone) {
  const width = Math.max(0, Math.min(100, percent)).toFixed(1);
  return '<div class="bar"><i class="' + (tone || "") + '" style="width:' + width + '%"></i></div>';
}

function renderStats(s) {
  const cells = [
    ["pull requests", s.pull_requests],
    ["runs", s.runs],
    ["decisions", s.decisions],
    ["high risk", s.high_risk],
    ["security review", s.security_review],
    ["failed runs", s.failed],
  ];
  document.getElementById("stats").innerHTML = cells
    .map(
      ([k, v]) =>
        '<div class="stat"><div class="k">' + esc(k) + '</div><div class="v">' + v + "</div></div>"
    )
    .join("");
}

function decisionRows(decisions) {
  return decisions
    .map((d) => {
      let percent;
      let value;
      if (d.question_type === "noul") {
        percent = parseFloat(d.answer) * 100;
        value = parseFloat(d.answer).toFixed(2);
      } else if (d.question_type === "score") {
        percent = d.level !== null && d.level !== undefined ? (d.level / 4) * 100 : 0;
        value = d.level !== null && d.level !== undefined ? "L" + d.level : d.answer;
      } else {
        percent = (d.confidence || 0) * 100;
        value = d.answer;
      }
      const tone =
        d.question_type === "noul" && parseFloat(d.answer) >= 0.7
          ? "bad"
          : d.question_type === "score" && d.level >= 3
            ? "warn"
            : "";
      return (
        '<div class="d"><div class="n">' +
        esc(d.question_name) +
        ' <span style="color:#4a5560">v' +
        d.question_version +
        "</span></div>" +
        bar(percent, tone) +
        '<div class="p">' +
        esc(value) +
        "</div></div>"
      );
    })
    .join("");
}

/* Filtering is client-side over data already fetched, so it stays instant and the
   stat strip keeps reporting the whole dataset rather than the filtered view. */

let ALL_ROWS = [];
let ACTIVE_FILTER = "all";
let QUERY = "";

function matchesFilter(row) {
  if (ACTIVE_FILTER === "attention") return row.highRisk || row.needsSec;
  if (ACTIVE_FILTER === "high") return row.highRisk;
  if (ACTIVE_FILTER === "security") return row.needsSec;
  if (ACTIVE_FILTER === "failed") return row.failed;
  return true;
}

function matchesQuery(row) {
  if (!QUERY) return true;
  const haystack = (
    row.pr.title + " " + row.pr.number + " " + row.pr.author + " " + row.pr.id
  ).toLowerCase();
  return haystack.indexOf(QUERY) !== -1;
}

function visibleRows() {
  return ALL_ROWS.filter((r) => matchesFilter(r) && matchesQuery(r));
}

function render() {
  const rows = visibleRows();
  const hint = document.getElementById("hint");
  hint.textContent =
    rows.length === ALL_ROWS.length
      ? ""
      : rows.length + " of " + ALL_ROWS.length + " shown";

  const sections = [
    ["Needs attention", rows.filter((r) => r.highRisk || r.needsSec), "review"],
    ["Evaluated", rows.filter((r) => !(r.highRisk || r.needsSec)), ""],
  ];

  document.getElementById("body").innerHTML = sections.length && rows.length
    ? sections
        .filter(([, list]) => list.length)
        .map(([name, list, tag]) =>
          '<div class="sec"><h2>' + esc(name) + '</h2><span class="count">' + list.length + "</span>" +
          (tag ? '<span class="tag">' + esc(tag) + "</span>" : "") + "</div>" +
          '<div class="grid">' +
          list.map((r, i) => card(r, i === 0 && r.highRisk)).join("") +
          "</div>"
        )
        .join("")
    : '<div class="empty"><b>Nothing matches</b>Clear the filter or the search to see the rest.</div>';
}

let FILTERS_WIRED = false;

function wireFilters() {
  // main() re-runs after a review, so without this each refresh would add another
  // click listener and a single chip press would re-render once per past render.
  if (FILTERS_WIRED) return;
  FILTERS_WIRED = true;
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
      chip.setAttribute("aria-pressed", "true");
      ACTIVE_FILTER = chip.dataset.filter;
      render();
    });
  });
  const search = document.getElementById("q");
  if (search) {
    search.addEventListener("input", (event) => {
      QUERY = event.target.value.trim().toLowerCase();
      render();
    });
  }
}

function decisionGraph(row) {
  const d = row.d;
  const risk = d.find((x) => x.question_name === "pr_risk");
  const cat = d.find((x) => x.question_name === "pr_category");
  const sec = d.find((x) => x.question_name === "pr_security_review");
  const level = risk ? risk.level : null;

  const contextTone = row.injection ? "bad" : "ok";
  const contextValue = row.injection
    ? "untrusted text flagged"
    : "context hashed · clean";

  const riskTone = level >= 4 ? "bad" : level >= 3 ? "warn" : "ok";
  const riskValue =
    level !== null && level !== undefined
      ? "L" + level + " " + (RISK_LABELS[level] || "")
      : "not measured";

  const actions = row.actions || [];
  const actionHtml = actions.length
    ? actions
        .map(
          (a) => '<span class="gact">' + esc(a.action_type) + " · " + esc(a.target) + "</span>"
        )
        .join("")
    : '<span class="gact" style="border-color:#2a323c;background:#12161b;color:#6b7783">no actions justified</span>';

  return (
    '<div class="graph">' +
    '<div class="gnode ' + contextTone + '"><div class="gk">context</div><div class="gv">' +
    esc(contextValue) + "</div></div>" +
    '<div class="gedge"></div>' +
    '<div class="gnode"><div class="gk">decisions · 6 typed</div><div class="gv">' +
    esc(cat ? cat.answer : "—") +
    " · security " +
    (sec ? parseFloat(sec.answer).toFixed(2) : "—") +
    " · testing " +
    (d.find((x) => x.question_name === "pr_additional_testing")
      ? parseFloat(d.find((x) => x.question_name === "pr_additional_testing").answer).toFixed(2)
      : "—") +
    "</div></div>" +
    '<div class="gedge"></div>' +
    '<div class="gnode ' + riskTone + '"><div class="gk">risk</div><div class="gv">' +
    esc(riskValue) +
    "</div></div>" +
    '<div class="gedge"></div>' +
    '<div class="gnode ' + (actions.length ? "warn" : "ok") + '"><div class="gk">actions</div>' +
    '<div class="gv" style="margin-top:5px">' + actionHtml + "</div></div>" +
    "</div>"
  );
}

function card(row, expanded) {
  const pr = row.pr;
  const d = row.d;
  const risk = d.find((x) => x.question_name === "pr_risk");
  const cat = d.find((x) => x.question_name === "pr_category");
  const sec = d.find((x) => x.question_name === "pr_security_review");
  const level = risk ? risk.level : null;

  const badges = [];
  if (cat) badges.push('<span class="b cat">' + esc(cat.answer) + "</span>");
  if (level !== null && level !== undefined) {
    const cls = level >= 4 ? "lvl3" : level === 3 ? "lvl2" : "lvl1";
    badges.push(
      '<span class="b ' + cls + '">risk L' + level + " " + esc(RISK_LABELS[level] || "") + "</span>"
    );
  }
  if (sec && parseFloat(sec.answer) >= 0.5) {
    badges.push('<span class="b security">security review</span>');
  }
  badges.push(
    '<span class="b ' + (pr.status === "failed" ? "fail" : "ok") + '">' + esc(pr.status) + "</span>"
  );

  return (
    '<article class="card" aria-expanded="' + (expanded ? "true" : "false") + '" tabindex="0">' +
    '<div class="ref"><b>#' + pr.number + "</b>" + esc(pr.author) + "</div>" +
    '<div class="mid">' +
    '<h3 class="title">' + esc(pr.title) + "</h3>" +
    '<div class="meta-line">' + esc(pr.repository || "repository") + " &middot; head " +
    esc((pr.head_sha || "").slice(0, 7) || "unknown") + "</div>" +
    '<div class="badges">' + badges.join("") + "</div>" +
    "</div>" +
    '<div class="detail">' + decisionGraph(row) + decisionRows(d) +
    '<div class="meta">' +
    "<span>run #" + d[0].run_id + "</span>" +
    "<span>status " + esc(pr.status) + "</span>" +
    "</div></div></article>"
  );
}

function toggle(el) {
  el.setAttribute("aria-expanded", el.getAttribute("aria-expanded") === "true" ? "false" : "true");
}

document.addEventListener("click", (event) => {
  const el = event.target.closest(".card");
  if (el) toggle(el);
});
document.addEventListener("keydown", (event) => {
  const el = event.target.closest(".card");
  if (el && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    toggle(el);
  }
});


/* Empty state.
   Deliberately does not read as an error. An empty database means "nothing has been
   reviewed yet", and the way out of that state is the form above, so the panel
   points at it rather than describing a webhook the reader may not control. */
function emptyState() {
  return (
    '<div class="empty">' +
    '<b>No evaluations yet</b>' +
    "Nothing has been reviewed, so there are no decisions to show. " +
    "Every figure on this page comes from a stored run, which is why the list is " +
    "empty rather than zero-filled." +
    '<div class="empty-go">Review a pull request above to create the first entry.</div>' +
    "</div>"
  );
}

/* On-demand review.
   Posts to /api/reviews and renders whatever comes back. The panel reports the
   run's real status: a failed evaluation is shown as failed with the reason,
   never smoothed over into an empty result, because a provider outage that looks
   like "no decisions" is exactly the failure this product must not have. */
function renderReviewResult(result) {
  const out = document.getElementById("review-out");
  out.hidden = false;
  const ok = result.status === "accepted";

  let decisions = "";
  if (result.decisions && result.decisions.length) {
    decisions =
      '<div class="rv-dec">' +
      result.decisions
        .map((d) => {
          const percent =
            d.type === "noul"
              ? parseFloat(d.answer) * 100
              : d.type === "score"
                ? ((d.level || 0) / 4) * 100
                : (d.confidence || 0) * 100;
          const value =
            d.type === "score" && d.level !== null && d.level !== undefined
              ? "L" + d.level + (d.label ? " " + shortLabel(d.label) : "")
              : d.type === "noul"
                ? parseFloat(d.answer).toFixed(2)
                : d.answer;
          return (
            '<div class="rv-row"><div class="rv-q">' + esc(d.question) + "</div>" +
            bar(percent, d.type === "noul" && parseFloat(d.answer) >= 0.7 ? "bad" : "") +
            '<div class="rv-v">' + esc(value) + "</div></div>"
          );
        })
        .join("") +
      "</div>";
  }

  const actions = (result.actions || []).length
    ? '<div class="rv-acts">' +
      result.actions
        .map(
          (a) =>
            '<span class="gact">' + esc(a.action_type) + " · " + esc(a.target) + "</span>"
        )
        .join("") +
      "</div>"
    : "";

  out.className = "review-out " + (ok ? "is-ok" : "is-bad");
  out.innerHTML =
    '<div class="rv-head"><b>' +
    (ok ? "Reviewed" : "Review failed") +
    "</b> " +
    esc(result.repository || "") +
    "#" +
    esc(result.number || "") +
    (result.title ? " · " + esc(result.title) : "") +
    "</div>" +
    '<div class="rv-detail">' + esc(result.detail || "") + "</div>" +
    (result.latency_ms ? '<div class="rv-meta">run #' + esc(result.run_id) + " · " + esc(result.latency_ms) + " ms</div>" : "") +
    (result.injection_flags && result.injection_flags.length
      ? '<div class="rv-warn">untrusted content flagged in: ' + esc(result.injection_flags.join(", ")) + "</div>"
      : "") +
    decisions +
    actions +
    (ok ? '<div class="rv-foot">Filed in the index below.</div>' : "");
}

let REVIEW_WIRED = false;

function wireReviewForm() {
  const form = document.getElementById("review-form");
  if (!form) return;
  // main() re-runs after a review to refresh the index, so this would otherwise
  // attach a second submit listener on every review and fire the request twice.
  if (REVIEW_WIRED) return;
  REVIEW_WIRED = true;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("review-go");
    const out = document.getElementById("review-out");
    const repository = document.getElementById("repo").value.trim();
    const number = parseInt(document.getElementById("prnum").value, 10);

    if (!repository || !number || number < 1) {
      out.hidden = false;
      out.className = "review-out is-bad";
      out.innerHTML = '<div class="rv-detail">Enter a repository as owner/name and a pull request number.</div>';
      return;
    }

    // A real model call takes seconds. The button says so rather than leaving the
    // reader watching a form that appears to have done nothing.
    button.disabled = true;
    button.textContent = "Reviewing…";
    out.hidden = false;
    out.className = "review-out is-busy";
    out.innerHTML = '<div class="rv-detail">Fetching the pull request and asking Jev…</div>';

    try {
      const response = await fetch("/api/reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ repository: repository, number: number }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || "HTTP " + response.status);
      }
      renderReviewResult(result);
      // Reload so the new run appears in the index instead of only in the panel.
      await main();
      const again = document.getElementById("review-out");
      if (again && again.innerHTML) again.hidden = false;
    } catch (err) {
      out.hidden = false;
      out.className = "review-out is-bad";
      out.innerHTML =
        '<div class="rv-head"><b>Could not review</b></div>' +
        '<div class="rv-detail">' + esc(err.message) + "</div>";
    } finally {
      button.disabled = false;
      button.textContent = "Review";
    }
  });
}

/* The API returns a score legend as a full sentence per level ("Moderate. Real
   behavioural change affecting known consumers."). That is the right text for a
   rubric and the wrong text for a narrow value column, where it wraps to five
   lines and pushes the whole row out of shape. Only the leading label is shown
   here; the full legend stays available on the card and in the API response. */
function shortLabel(text) {
  if (!text) return "";
  const head = String(text).split(".")[0].trim();
  return head.length > 24 ? head.slice(0, 23) + "…" : head;
}

async function main() {
  const body = document.getElementById("body");
  wireReviewForm();
  try {
    const health = await get("/api/health");
    const live = document.getElementById("live");
    document.getElementById("prov").textContent =
      health.model + " · " + health.transport +
      (health.credentials_configured ? "" : " · no credentials");
    // The pill states whether the decision layer is *configured*, never whether it
    // is reachable: /api/health deliberately does not call the model. So a green
    // dot here means "wired up", and a real outage is reported by a failed run
    // instead of being hidden behind a probe.
    if (health.credentials_configured) live.classList.add("is-ok");
    else live.classList.add("is-warn");

    const prs = await get("/api/pull-requests?limit=100");
    if (!prs.length) {
      body.innerHTML = emptyState();
      renderStats({ pull_requests: 0, runs: 0, decisions: 0, high_risk: 0, security_review: 0, failed: 0 });
      ALL_ROWS = [];
      wireFilters();
      return;
    }

    const decisions = await Promise.all(
      prs.map((p) => get("/api/pull-requests/" + p.id + "/decisions"))
    );
    const details = await Promise.all(prs.map((p) => get("/api/pull-requests/" + p.id)));
    const graphs = await Promise.all(
      prs.map((p) => get("/api/pull-requests/" + p.id + "/graph").catch(() => null))
    );

    const rows = prs.map((pr, i) => {
      const d = decisions[i];
      const risk = d.find((x) => x.question_name === "pr_risk");
      const sec = d.find((x) => x.question_name === "pr_security_review");
      const graph = graphs[i];
      return {
        pr,
        d,
        level: risk ? risk.level : -1,
        highRisk: Boolean(risk && risk.level >= 3),
        needsSec: Boolean(sec && parseFloat(sec.answer) >= 0.5),
        failed: (details[i].runs || []).some((r) => r.status === "failed"),
        actions: graph ? graph.actions : [],
        injection: graph ? (graph.context.injection_flags || []).length > 0 : false,
      };
    });

    renderStats({
      pull_requests: rows.length,
      runs: details.reduce((n, x) => n + (x.runs || []).length, 0),
      decisions: rows.reduce((n, r) => n + r.d.length, 0),
      high_risk: rows.filter((r) => r.highRisk).length,
      security_review: rows.filter((r) => r.needsSec).length,
      failed: rows.filter((r) => r.failed).length,
    });

    ALL_ROWS = rows;
    wireFilters();
    render();
  } catch (err) {
    body.innerHTML =
      '<div class="empty"><b>Could not reach the API</b>' + esc(err.message) +
      "<br><br>Start the server with <code>uvicorn app.main:app</code> and reload.</div>";
  }
}

main();
