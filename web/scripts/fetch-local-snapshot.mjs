import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const base = process.env.FLUO_LOCAL_URL ?? "http://127.0.0.1:8876";
const output = resolve(process.env.FLUO_SNAPSHOT_PATH ?? "public/data/snapshot.json");

async function get(path) {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

const [summary, companyPayload] = await Promise.all([
  get("/api/summary"),
  get("/api/companies"),
]);

const jobs = [];
const pageSize = 250;
for (let offset = 0; offset < summary.active_jobs; offset += pageSize) {
  const payload = await get(`/api/jobs?sort=recent&limit=${pageSize}&offset=${offset}`);
  jobs.push(...payload.jobs);
  if (payload.jobs.length < pageSize) break;
}

await mkdir(dirname(output), { recursive: true });
await writeFile(
  output,
  JSON.stringify(
    {
      captured_at: summary.latest_run?.completed_at ?? new Date().toISOString(),
      summary,
      companies: companyPayload.companies,
      jobs,
    },
    null,
    2,
  ),
);

console.log(`Wrote ${jobs.length} jobs from ${companyPayload.companies.length} employers to ${output}`);
