import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectRoot = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", String(process.pid) + "-" + Date.now());
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the finished Fluo page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Fluo — Sponsor signal, before the crowd<\/title>/i);
  assert.match(html, /Loading the verified job snapshot/i);
  assert.doesNotMatch(html, /Starter Project|Your site is taking shape|codex-preview/i);
});

test("checked-in snapshot is complete and internally consistent", async () => {
  const snapshot = JSON.parse(
    await readFile(new URL("public/data/snapshot.json", projectRoot), "utf8"),
  );

  assert.equal(snapshot.summary.active_jobs, 8_145);
  assert.equal(snapshot.summary.verified_companies, 31);
  assert.equal(snapshot.jobs.length, snapshot.summary.active_jobs);
  assert.equal(snapshot.companies.length, 31);
  assert.equal(new Set(snapshot.jobs.map((job) => job.id)).size, snapshot.jobs.length);
  assert.ok(snapshot.jobs.every((job) => /^https:\/\//.test(job.external_url)));
});
