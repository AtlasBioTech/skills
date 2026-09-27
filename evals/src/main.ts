#!/usr/bin/env bun
// atlas-evals: which model, driven by OpenCode in the Atlas workspace, can do
// a scenario? See ../README.md.
//
//   atlas-evals run --scenario tp53-r175h --models a,b --runs 5
//   atlas-evals list-models
//   atlas-evals summarize runs/<timestamp>

import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { removeLabelled } from "./docker";
import { summarize, type RunRecord } from "./report";
import { runOne } from "./run";
import { loadScenario } from "./scenario";

const ROOT = resolve(import.meta.dir, "..");
const DEFAULT_BASE_URL = "https://api.scaleway.ai/v1";

const USAGE = `usage:
  atlas-evals run --scenario <id> --models <m1,m2,…> [--runs 3] [options]
  atlas-evals list-models [--base-url <url>]
  atlas-evals summarize <runs/timestamp directory>

The API key is read from ATLAS_LLM_API_KEY (or SCW_SECRET_KEY); it is passed to
the workspaces through the environment and never written anywhere.

run options:
  --base-url <url>          OpenAI-compatible endpoint ending in /v1 (default: $ATLAS_LLM_BASE_URL or ${DEFAULT_BASE_URL})
  --provider <label>        shown as the model provider in the workspace (default: the endpoint's host)
  --image <name>            workspace image (default: atlas-workspace)
  --network <name>          docker network shared with this runner (default: atlas-evals-net)
  --prefix <name>           container name prefix (default: atlas-evals)
  --concurrency <n>         workspaces at the same time (default: 1)
  --cpus <n> --memory <m>   limits per workspace (default: 2, 3g)
  --startup-timeout <s>     wait for the bridge's /healthz (default: 180)
  --out <dir>               where runs/<timestamp>/ goes (default: ${join(ROOT, "runs")})`;

async function main(argv: string[]): Promise<number> {
  const [command, ...rest] = argv;
  switch (command) {
    case "run":
      return run(rest);
    case "list-models":
      return listModels(rest);
    case "summarize":
      return summarizeDir(rest);
    default:
      console.log(USAGE);
      return command === "help" || command === "--help" ? 0 : 2;
  }
}

function apiKey(): string | undefined {
  return process.env.ATLAS_LLM_API_KEY || process.env.SCW_SECRET_KEY || undefined;
}

/** Replaces the API key wherever it might have been echoed (errors, logs). */
function makeRedactor(key: string | undefined): (text: string) => string {
  if (!key || key.length < 6) return (text) => text;
  return (text) => text.split(key).join("[REDACTED]");
}

async function run(args: string[]): Promise<number> {
  const { values } = parseArgs({
    args,
    options: {
      scenario: { type: "string" },
      models: { type: "string" },
      runs: { type: "string", default: "3" },
      "base-url": { type: "string", default: process.env.ATLAS_LLM_BASE_URL || DEFAULT_BASE_URL },
      provider: { type: "string" },
      image: { type: "string", default: "atlas-workspace" },
      network: { type: "string", default: "atlas-evals-net" },
      prefix: { type: "string", default: "atlas-evals" },
      concurrency: { type: "string", default: "1" },
      cpus: { type: "string", default: "2" },
      memory: { type: "string", default: "3g" },
      "startup-timeout": { type: "string", default: "180" },
      out: { type: "string", default: join(ROOT, "runs") },
      help: { type: "boolean", short: "h" },
    },
  });
  if (values.help) {
    console.log(USAGE);
    return 0;
  }
  if (!values.scenario || !values.models) {
    console.error(USAGE);
    return 2;
  }
  const scenario = loadScenario(join(ROOT, "scenarios"), values.scenario);
  const models = values.models.split(",").map((m) => m.trim()).filter(Boolean);
  const runs = positiveInt(values.runs, "--runs");
  const concurrency = positiveInt(values.concurrency, "--concurrency");
  const baseUrl = values["base-url"].replace(/\/+$/, "");
  const key = apiKey();
  if (!key) console.error("warning: no ATLAS_LLM_API_KEY / SCW_SECRET_KEY set; sending the placeholder key \"none\"");
  const redact = makeRedactor(key);

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");
  const outDir = join(values.out, stamp);
  mkdirSync(outDir, { recursive: true });
  const jsonl = join(outDir, "runs.jsonl");
  const label = `${values.prefix}-${stamp}`;

  // Ctrl-C must not leave workspaces running on a shared host.
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, async () => {
      console.error(`\n${signal}: removing this batch's workspaces…`);
      await removeLabelled(label);
      process.exit(130);
    });
  }

  // Attempt-major order: every model gets its first run before any gets its
  // second, so a slow patch on the endpoint hurts all models alike.
  const jobs = Array.from({ length: runs }, (_, i) => models.map((model) => ({ model, attempt: i + 1 }))).flat();
  console.log(`${scenario.id}: ${models.length} model(s) × ${runs} run(s) against ${baseUrl}, ${concurrency} at a time → ${outDir}`);

  const records: RunRecord[] = [];
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const job = jobs[next]!;
      const n = ++next;
      const runId = `${String(n).padStart(3, "0")}-${slug(job.model)}-${job.attempt}`;
      const log = (line: string) => console.log(`[${runId}] ${redact(line)}`);
      log(`start (${job.model}, run ${job.attempt}/${runs})`);
      const record = await runOne({
        scenario,
        model: job.model,
        attempt: job.attempt,
        runId,
        outDir,
        containerName: `${values.prefix}-ws-${stamp}-${String(n).padStart(3, "0")}`,
        bridgePort: 7070,
        startupTimeoutMs: positiveInt(values["startup-timeout"], "--startup-timeout") * 1000,
        workspace: {
          image: values.image,
          network: values.network,
          label,
          cpus: values.cpus,
          memory: values.memory,
          baseUrl,
          provider: values.provider ?? new URL(baseUrl).host,
          apiKey: key ?? "none",
        },
        redact,
        log,
      });
      records.push(record);
      appendFileSync(jsonl, JSON.stringify(record) + "\n");
      log(record.pass ? `PASS in ${record.metrics.wall_s} s` : `FAIL: ${record.failure} — ${record.checks.find((c) => !c.pass)?.detail ?? ""}`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, jobs.length) }, worker));

  records.sort((a, b) => a.run_id.localeCompare(b.run_id));
  writeFileSync(jsonl, records.map((r) => JSON.stringify(r)).join("\n") + "\n");
  const summary = summarize(records, scenario.id);
  writeFileSync(join(outDir, "summary.md"), summary);
  console.log(`\n${summary}\nruns: ${jsonl}\nsummary: ${join(outDir, "summary.md")}`);
  return 0;
}

async function listModels(args: string[]): Promise<number> {
  const { values } = parseArgs({
    args,
    options: { "base-url": { type: "string", default: process.env.ATLAS_LLM_BASE_URL || DEFAULT_BASE_URL } },
  });
  const url = `${values["base-url"].replace(/\/+$/, "")}/models`;
  const key = apiKey();
  const res = await fetch(url, { headers: key ? { Authorization: `Bearer ${key}` } : {} });
  if (!res.ok) {
    console.error(`GET ${url}: HTTP ${res.status} ${makeRedactor(key)((await res.text()).slice(0, 300))}`);
    return 1;
  }
  const body = (await res.json()) as { data?: { id: string; owned_by?: string }[] };
  const ids = (body.data ?? []).map((m) => m.id).sort();
  for (const id of ids) console.log(id);
  console.error(`${ids.length} model(s) at ${url}`);
  return 0;
}

function summarizeDir(args: string[]): number {
  const dir = args[0];
  if (!dir) {
    console.error(USAGE);
    return 2;
  }
  const records = readFileSync(join(dir, "runs.jsonl"), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as RunRecord);
  const scenarios = [...new Set(records.map((r) => r.scenario))];
  for (const s of scenarios) console.log(summarize(records.filter((r) => r.scenario === s), s));
  return 0;
}

function positiveInt(value: string, flag: string): number {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 1) throw new Error(`${flag} must be a positive integer, got ${value}`);
  return n;
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9.]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
}

main(Bun.argv.slice(2)).then(
  (code) => process.exit(code),
  (err) => {
    console.error(`atlas-evals: ${(err as Error).message}`);
    process.exit(1);
  },
);
