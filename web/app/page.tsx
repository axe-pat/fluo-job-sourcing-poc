"use client";

import { useEffect, useMemo, useState } from "react";

type Company = {
  name: string;
  ats_type: string;
  approval_count: number;
  approval_rate: number;
  approval_rate_percent: number;
  active_job_count: number;
  hq_location: string;
};

type Job = {
  id: string;
  title: string;
  company: string;
  location: string;
  department: string;
  ats_type: string;
  approval_count: number;
  approval_rate_percent: number;
  posted_date: string | null;
  date_provenance: "published_at" | "updated_at" | "relative_posted" | "first_seen";
  first_seen_at: string;
  external_url: string;
};

type Snapshot = {
  captured_at: string;
  summary: {
    active_jobs: number;
    new_24h: number;
    companies_with_jobs: number;
    verified_companies: number;
    latest_run: {
      companies_succeeded: number;
      companies_total: number;
      companies_failed: number;
    } | null;
  };
  companies: Company[];
  jobs: Job[];
};

const PAGE_SIZE = 100;

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function captureDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

function relativeTo(value: string | null, capturedAt: string) {
  if (!value) return "Unknown";
  const seconds = Math.max(0, Math.floor((new Date(capturedAt).getTime() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "At capture";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m before capture`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h before capture`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d before capture`;
  return `${Math.floor(days / 30)}mo before capture`;
}

function provenanceLabel(value: Job["date_provenance"]) {
  return {
    published_at: "ATS published",
    updated_at: "ATS updated",
    relative_posted: "ATS posted",
    first_seen: "First seen",
  }[value];
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
}

export default function Home() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [company, setCompany] = useState("");
  const [approval, setApproval] = useState(0);
  const [age, setAge] = useState(0);
  const [sort, setSort] = useState("recent");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [notice, setNotice] = useState(false);

  useEffect(() => {
    fetch("/data/snapshot.json")
      .then((response) => {
        if (!response.ok) throw new Error("The demo snapshot could not be loaded.");
        return response.json();
      })
      .then(setSnapshot)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "The snapshot could not be loaded."));
  }, []);

  const filtered = useMemo(() => {
    if (!snapshot) return [];
    const needle = search.trim().toLocaleLowerCase();
    const captured = new Date(snapshot.captured_at).getTime();
    const rows = snapshot.jobs.filter((job) => {
      if (company && job.company !== company) return false;
      if (approval && job.approval_rate_percent < approval) return false;
      const jobDate = new Date(job.posted_date || job.first_seen_at).getTime();
      if (age && captured - jobDate > age * 86_400_000) return false;
      if (!needle) return true;
      return `${job.title} ${job.company} ${job.location} ${job.department}`.toLocaleLowerCase().includes(needle);
    });

    return rows.sort((a, b) => {
      if (sort === "approval") return b.approval_rate_percent - a.approval_rate_percent || b.approval_count - a.approval_count;
      if (sort === "company") return a.company.localeCompare(b.company) || a.title.localeCompare(b.title);
      if (sort === "first_seen") return new Date(b.first_seen_at).getTime() - new Date(a.first_seen_at).getTime();
      return new Date(b.posted_date || b.first_seen_at).getTime() - new Date(a.posted_date || a.first_seen_at).getTime();
    });
  }, [snapshot, search, company, approval, age, sort]);

  if (error) {
    return (
      <main className="state-page">
        <div className="state-card"><span>!</span><h1>Demo unavailable</h1><p>{error}</p></div>
      </main>
    );
  }

  if (!snapshot) {
    return (
      <main className="state-page">
        <div className="loading-mark"><i /><i /><i /></div>
        <p>Loading the verified job snapshot…</p>
      </main>
    );
  }

  const run = snapshot.summary.latest_run;

  return (
    <>
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />

      <header className="site-header">
        <a className="brand" href="#top" aria-label="Fluo job sourcing demo home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>fluo</span>
        </a>
        <div className="header-actions">
          <span className="system-status"><i /><span>{run?.companies_succeeded}/{run?.companies_total} feeds verified</span></span>
          <button className="snapshot-button" type="button" onClick={() => setNotice(true)}>About this snapshot</button>
        </div>
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <div className="eyebrow"><span>LA / SOUTHERN CALIFORNIA</span><b>SHAREABLE POC</b></div>
            <h1 id="hero-title">The sponsor signal.<br /><em>Before the crowd.</em></h1>
            <p>Fresh openings from employers with recent H-1B history, pulled from their public hiring systems. No LinkedIn scraping. No ranking algorithm. Just a focused watchlist.</p>
            <div className="hero-meta"><span>Snapshot captured {captureDate(snapshot.captured_at)}</span><span>Company-wide roles · global locations</span></div>
          </div>
          <aside className="signal-card" aria-label="Data sourcing promise">
            <div className="signal-orbit" aria-hidden="true"><span /></div>
            <div><small>Source integrity</small><strong>Public feed only</strong><p>Greenhouse · Lever · Ashby · Workday stretch</p></div>
            <span className="zero-badge">0 scraping</span>
          </aside>
        </section>

        <section className="trust-strip" aria-label="Prototype guarantees">
          <span><i>✓</i> Public ATS JSON</span>
          <span><i>✓</i> DOL sponsor history</span>
          <span><i>✓</i> First-seen preserved</span>
          <span><i>◇</i> No login sessions</span>
        </section>

        <section className="metric-grid" aria-label="Job source summary">
          <article className="metric-card metric-primary"><b>↗</b><div><strong>{formatNumber(snapshot.summary.active_jobs)}</strong><span>Live openings</span></div><p>At snapshot capture</p></article>
          <article className="metric-card"><b>◎</b><div><strong>{snapshot.summary.verified_companies}</strong><span>Verified employers</span></div><p>31 reviewed feed mappings</p></article>
          <article className="metric-card"><b>✦</b><div><strong>{snapshot.summary.companies_with_jobs}</strong><span>With openings</span></div><p>One healthy feed was empty</p></article>
          <article className="metric-card"><b>◷</b><div><strong>{run?.companies_failed ? `${run.companies_failed}` : "0"}</strong><span>Failed feeds</span></div><p>On the verified run</p></article>
        </section>

        <section className="jobs-shell" aria-labelledby="jobs-title">
          <div className="section-heading"><div><span>THE WATCHLIST</span><h2 id="jobs-title">Sponsor-history employer roles</h2></div><p>{formatNumber(filtered.length)} roles found</p></div>

          <div className="filters" role="search">
            <label className="search-box"><span aria-hidden="true">⌕</span><span className="sr-only">Search roles</span><input type="search" placeholder="Search title, team, location…" value={search} onChange={(event) => { setSearch(event.target.value); setVisible(PAGE_SIZE); }} /></label>
            <label><span className="sr-only">Company</span><select value={company} onChange={(event) => { setCompany(event.target.value); setVisible(PAGE_SIZE); }}><option value="">All companies</option>{snapshot.companies.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.active_job_count})</option>)}</select></label>
            <label><span className="sr-only">Minimum LCA approval rate</span><select value={approval} onChange={(event) => { setApproval(Number(event.target.value)); setVisible(PAGE_SIZE); }}><option value="0">Any approval rate</option><option value="90">90%+ approval</option><option value="95">95%+ approval</option><option value="100">100% approval</option></select></label>
            <label><span className="sr-only">Role age at snapshot</span><select value={age} onChange={(event) => { setAge(Number(event.target.value)); setVisible(PAGE_SIZE); }}><option value="0">Any ATS date</option><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select></label>
            <label><span className="sr-only">Sort order</span><select value={sort} onChange={(event) => { setSort(event.target.value); setVisible(PAGE_SIZE); }}><option value="recent">Newest ATS date</option><option value="first_seen">Newest first seen</option><option value="approval">Highest approval</option><option value="company">Company A–Z</option></select></label>
          </div>

          <div className="job-list">
            {filtered.slice(0, visible).map((job) => (
              <article className="job-row" key={job.id}>
                <div className="company-avatar" aria-hidden="true">{initials(job.company)}</div>
                <div className="job-main"><h3>{job.title}</h3><p><b>{job.company}</b><span>{job.ats_type}</span></p></div>
                <div className="job-meta"><small>Location</small><span>{job.location}</span></div>
                <div className="job-meta"><small>Team</small><span>{job.department}</span></div>
                <span className="signal-pill" title="Company-level DOL LCA approval rate and certified-record count">{job.approval_rate_percent.toFixed(job.approval_rate_percent % 1 ? 1 : 0)}% · {job.approval_count} LCA</span>
                <div className="job-date"><strong>{relativeTo(job.posted_date || job.first_seen_at, snapshot.captured_at)}</strong><small>{provenanceLabel(job.date_provenance)}</small></div>
                <a className="job-link" href={job.external_url} target="_blank" rel="noreferrer" aria-label={`Open ${job.title} at ${job.company}`}>↗</a>
              </article>
            ))}
            {!filtered.length && <div className="empty-state"><i>⌁</i><h3>No roles match this view</h3><p>Try broadening the company, date, or approval-rate filters.</p></div>}
          </div>

          {visible < filtered.length && <button className="load-more" type="button" onClick={() => setVisible((count) => count + PAGE_SIZE)}>Show {Math.min(PAGE_SIZE, filtered.length - visible)} more roles</button>}
        </section>

        <section className="context-grid">
          <article><span>01</span><div><h3>Employer signal, not a promise</h3><p>An LCA is a DOL filing made before the H-1B petition process. It shows recent employer history; it does not guarantee sponsorship for a listed role.</p></div></article>
          <article><span>02</span><div><h3>Curated coverage</h3><p>The POC verifies 31 feeds from a 230-employer SoCal seed. This is a coverage floor, not proof that all remaining employers lack public feeds.</p></div></article>
          <article><span>03</span><div><h3>Live loop is local</h3><p>The working local system performs recurring refreshes and preserves first-seen timestamps. This public demo is a fixed, verified snapshot for safe sharing.</p></div></article>
        </section>
      </main>

      <footer><div><span>f</span><p><strong>Fluo sourcing prototype</strong><br />A narrow proof that “first to know” can be safe and cheap.</p></div><p>Source: U.S. DOL LCA disclosure · public ATS feeds</p></footer>

      {notice && <div className="modal-backdrop" role="presentation" onMouseDown={() => setNotice(false)}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="snapshot-title" onMouseDown={(event) => event.stopPropagation()}><button type="button" aria-label="Close" onClick={() => setNotice(false)}>×</button><span>SHAREABLE DEMO</span><h2 id="snapshot-title">A verified snapshot, not a live service</h2><p>This hosted version contains the complete August 5, 2026 dataset so filters and job links can be shared safely. The local prototype owns recurring public-feed refreshes and durable first-seen history.</p><p>Company sponsorship history is based on scoped DOL LCA records. It is not a guarantee that any individual job sponsors.</p></div></div>}
    </>
  );
}
