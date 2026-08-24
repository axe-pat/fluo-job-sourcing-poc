const state = {
  companies: [],
  jobs: [],
  summary: null,
  searchTimer: null,
  toastTimer: null,
};

const $ = (selector) => document.querySelector(selector);

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function number(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function relativeTime(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

function provenanceLabel(value) {
  return {
    published_at: "Published",
    updated_at: "ATS updated",
    relative_posted: "ATS posted",
    first_seen: "First seen",
  }[value] || "ATS date";
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join("");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 3800);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function setStatus(latestRun, running = false) {
  const element = $("#system-status");
  element.classList.remove("healthy", "partial");
  if (running) {
    element.querySelector("span").textContent = "Refreshing feeds";
    return;
  }
  if (!latestRun) {
    element.querySelector("span").textContent = "Ready for first run";
    return;
  }
  const failures = Number(latestRun.companies_failed || 0);
  element.classList.add(failures ? "partial" : "healthy");
  element.querySelector("span").textContent = failures ? `${failures} feed${failures === 1 ? "" : "s"} need review` : "All feeds healthy";
}

function renderSummary(summary) {
  state.summary = summary;
  $("#metric-jobs").textContent = number(summary.active_jobs);
  $("#metric-companies").textContent = number(summary.verified_companies);
  $("#metric-new").textContent = number(summary.new_24h);
  const run = summary.latest_run;
  $("#metric-refresh").textContent = run?.completed_at ? relativeTime(run.completed_at) : "Not run";
  if (run) {
    const healthy = Number(run.companies_succeeded || 0);
    const total = Number(run.companies_total || 0);
    $("#metric-health").textContent = `${healthy}/${total} public feeds responded`;
  }
  setStatus(run);
}

function populateCompanies(companies) {
  state.companies = companies;
  const select = $("#company-filter");
  const current = select.value;
  select.replaceChildren(new Option("All companies", ""));
  companies.forEach((company) => {
    const label = `${company.name} (${number(company.active_job_count)})`;
    select.add(new Option(label, company.name));
  });
  select.value = current;
}

function renderJobs(payload) {
  state.jobs = payload.jobs;
  const list = $("#job-list");
  list.setAttribute("aria-busy", "false");
  list.replaceChildren();
  $("#result-count").textContent = `${number(payload.total)} role${payload.total === 1 ? "" : "s"} found`;
  if (!payload.jobs.length) {
    const empty = make("div", "empty-state");
    empty.append(make("i", "", "⌁"), make("h3", "", "No roles match this view"));
    const message = state.summary?.latest_run
      ? "Try broadening the company, date, or approval-rate filters."
      : "Run the first public-feed refresh to populate the watchlist.";
    empty.append(make("p", "", message));
    list.append(empty);
    return;
  }

  payload.jobs.forEach((job) => {
    const row = make("article", "job-row");
    row.append(make("div", "company-avatar", initials(job.company)));

    const main = make("div", "job-main");
    main.append(make("h3", "", job.title));
    const companyLine = make("p");
    companyLine.append(make("b", "", job.company), make("span", "ats-tag", job.ats_type));
    main.append(companyLine);
    row.append(main);

    const location = make("div", "job-meta");
    location.append(make("small", "", "Location"), make("span", "", job.location));
    row.append(location);

    const department = make("div", "job-meta");
    department.append(make("small", "", "Team"), make("span", "", job.department));
    row.append(department);

    const rate = Number(job.approval_rate_percent || 0);
    const signal = make("span", `signal-pill${rate < 90 ? " low" : ""}`, `${rate.toFixed(rate % 1 ? 1 : 0)}% · ${number(job.approval_count)} LCA`);
    signal.title = "DOL LCA approval rate and approved-case count for the scoped period";
    row.append(signal);

    const date = make("div", "job-date");
    const dateValue = job.posted_date || job.first_seen_at;
    date.append(make("strong", "", relativeTime(dateValue)), make("small", "", provenanceLabel(job.date_provenance)));
    row.append(date);

    const link = make("a", "job-link");
    link.href = job.external_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.setAttribute("aria-label", `Open ${job.title} at ${job.company}`);
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M7 17 17 7M8 7h9v9");
    icon.append(path);
    link.append(icon);
    row.append(link);
    list.append(row);
  });
}

async function loadJobs() {
  const params = new URLSearchParams();
  const mappings = [
    ["q", $("#search-input").value.trim()],
    ["company", $("#company-filter").value],
    ["min_approval_rate", $("#approval-filter").value],
    ["age_days", $("#age-filter").value],
    ["sort", $("#sort-filter").value],
  ];
  mappings.forEach(([key, value]) => { if (value) params.set(key, value); });
  params.set("limit", "100");
  try {
    renderJobs(await api(`/api/jobs?${params.toString()}`));
  } catch (error) {
    $("#job-list").replaceChildren();
    const empty = make("div", "empty-state");
    empty.append(make("i", "", "!"), make("h3", "", "Could not load the watchlist"), make("p", "", error.message));
    $("#job-list").append(empty);
  }
}

async function loadDashboard() {
  try {
    const [summary, companies] = await Promise.all([api("/api/summary"), api("/api/companies")]);
    renderSummary(summary);
    populateCompanies(companies.companies);
    await loadJobs();
  } catch (error) {
    showToast(error.message);
    await loadJobs();
  }
}

async function refreshNow() {
  const button = $("#refresh-button");
  button.disabled = true;
  button.classList.add("loading");
  setStatus(state.summary?.latest_run, true);
  try {
    await api("/api/refresh", { method: "POST" });
    showToast("Public ATS refresh started");
    const deadline = Date.now() + 420000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1800));
      const health = await api("/api/health");
      if (!health.refresh_running) {
        await loadDashboard();
        showToast("Watchlist refreshed");
        return;
      }
    }
    showToast("Refresh is still running in the background");
  } catch (error) {
    if (error.message.includes("already")) showToast("A refresh is already running");
    else showToast(error.message);
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    setStatus(state.summary?.latest_run);
  }
}

$("#search-input").addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(loadJobs, 220);
});
["#company-filter", "#approval-filter", "#age-filter", "#sort-filter"].forEach((selector) => {
  $(selector).addEventListener("change", loadJobs);
});
$("#refresh-button").addEventListener("click", refreshNow);
$("#decision-toggle").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  $("#decision-content").hidden = expanded;
});

loadDashboard();
