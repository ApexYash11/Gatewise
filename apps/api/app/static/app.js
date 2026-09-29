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
    badges.push('<span class="b sec">security review</span>');
  }
  badges.push(
    '<span class="b ' + (pr.status === "failed" ? "fail" : "ok") + '">' + esc(pr.status) + "</span>"
  );

  return (
    '<article class="card" aria-expanded="' +
    (expanded ? "true" : "false") +
    '" tabindex="0">' +
    '<div class="row1"><span class="repo">#' + pr.number + " · " + esc(pr.author) + "</span></div>" +
    '<div class="title">' + esc(pr.title) + "</div>" +
    '<div class="badges">' + badges.join("") + "</div>" +
    '<div class="detail">' + decisionRows(d) +
    '<div class="meta">' +
    "<span>run #" + d[0].run_id + "</span>" +
    "<span>head " + esc((pr.head_sha || "").slice(0, 7)) + "</span>" +
    "<span>" + esc(pr.status) + "</span>" +
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

    .join("");
}


async function main() {
  const body = document.getElementById("body");
  try {
    const health = await get("/api/health");
    document.getElementById("prov").textContent =
      health.model + " · " + health.transport +
      (health.credentials_configured ? "" : " · no credentials");

    const prs = await get("/api/pull-requests?limit=100");
    if (!prs.length) {
      body.innerHTML =
        '<div class="empty"><b>No evaluations yet</b>' +
        "Send a signed webhook to <code>POST /webhooks/github</code> to record a decision.</div>";
      renderStats({ pull_requests: 0, runs: 0, decisions: 0, high_risk: 0, security_review: 0, failed: 0 });
      return;
    }

    const decisions = await Promise.all(
      prs.map((p) => get("/api/pull-requests/" + p.id + "/decisions"))
    );
    const details = await Promise.all(prs.map((p) => get("/api/pull-requests/" + p.id)));

    const rows = prs.map((pr, i) => {
      const d = decisions[i];
      const risk = d.find((x) => x.question_name === "pr_risk");
      const sec = d.find((x) => x.question_name === "pr_security_review");
      return {
        pr,
        d,
        level: risk ? risk.level : -1,
        highRisk: Boolean(risk && risk.level >= 3),
        needsSec: Boolean(sec && parseFloat(sec.answer) >= 0.5),
      };
    });

    renderStats({
      pull_requests: rows.length,
      runs: details.reduce((n, x) => n + (x.runs || []).length, 0),
      decisions: rows.reduce((n, r) => n + r.d.length, 0),
      high_risk: rows.filter((r) => r.highRisk).length,
      security_review: rows.filter((r) => r.needsSec).length,
      failed: details.filter((x) => (x.runs || []).some((r) => r.status === "failed")).length,
    });

    const sections = [
      ["Needs attention", rows.filter((r) => r.highRisk || r.needsSec), "review"],
      ["Evaluated", rows.filter((r) => !(r.highRisk || r.needsSec)), ""],
    ];

    body.innerHTML = sections
      .filter(([, list]) => list.length)
      .map(([name, list, tag]) =>
        '<div class="sec"><h2>' + esc(name) + '</h2><span class="count">' + list.length + "</span>" +
        (tag ? '<span class="tag">' + esc(tag) + "</span>" : "") + "</div>" +
        '<div class="grid">' +
        list.map((r, i) => card(r, i === 0 && r.highRisk)).join("") +
        "</div>"
      )
      .join("");
  } catch (err) {
    body.innerHTML =
      '<div class="empty"><b>Could not reach the API</b>' + esc(err.message) +
      "<br><br>Start the server with <code>uvicorn app.main:app</code> and reload.</div>";
  }
}

main();
