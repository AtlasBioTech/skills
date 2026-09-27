// One run: a fresh workspace for one model, the scenario's prompts, the
// graders, the teardown. Everything the run produced is kept next to its record
// so a failure can be read without re-running it.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { execIn, logsOf, readFileIn, removeContainer, startWorkspace, waitHealthy, type WorkspaceSpec } from "./docker";
import { grade, type Observation } from "./graders";
import type { RunRecord, Tokens } from "./report";
import type { Scenario } from "./scenario";
import { runSession, toolStats, type Frame, type SessionResult } from "./session";

export type RunConfig = {
  scenario: Scenario;
  model: string;
  attempt: number;
  runId: string;
  outDir: string;
  workspace: Omit<WorkspaceSpec, "name" | "model">;
  containerName: string;
  bridgePort: number;
  startupTimeoutMs: number;
  redact: (text: string) => string;
  log: (line: string) => void;
};

export async function runOne(cfg: RunConfig): Promise<RunRecord> {
  const { scenario, redact, log } = cfg;
  const name = cfg.containerName;
  const artifacts = join(cfg.outDir, cfg.runId);
  mkdirSync(artifacts, { recursive: true });
  const startedAt = new Date();

  const record: RunRecord = {
    run_id: cfg.runId,
    scenario: scenario.id,
    model: cfg.model,
    base_url: cfg.workspace.baseUrl,
    attempt: cfg.attempt,
    started_at: startedAt.toISOString(),
    pass: false,
    failure: null,
    checks: [],
    metrics: {
      startup_s: null,
      wall_s: null,
      turns: [],
      tool_calls: 0,
      tool_calls_failed: 0,
      tool_calls_by_kind: {},
      permissions: [],
      tokens: null,
    },
    errors: [],
    answer: "",
    artifacts,
  };

  try {
    const t0 = performance.now();
    await startWorkspace({ ...cfg.workspace, name, model: cfg.model });
    await waitHealthy(name, cfg.bridgePort, cfg.startupTimeoutMs);
    record.metrics.startup_s = round((performance.now() - t0) / 1000);
    log(`workspace ready in ${record.metrics.startup_s} s`);

    const notebookBefore = await readFileIn(name, scenario.notebook.path);
    const t1 = performance.now();
    const session = await runSession({
      url: `ws://${name}:${cfg.bridgePort}/ws`,
      prompts: scenario.prompts,
      timeoutMs: scenario.timeout_s * 1000,
      onFrame: (f) => logFrame(f, log),
    });
    record.metrics.wall_s = round((performance.now() - t1) / 1000);

    const notebookAfter = await readFileIn(name, scenario.notebook.path);
    const notebookRun = scenario.notebook.must_run && notebookAfter !== null ? await runNotebook(name, scenario) : null;
    if (notebookRun) log(`notebook ${notebookRun.exitCode === 0 ? "runs" : `fails (exit ${notebookRun.exitCode})`} in ${round(notebookRun.seconds)} s`);

    const obs: Observation = { turns: session.turns, errors: session.errors, notebookBefore, notebookAfter, notebookRun };
    record.checks = grade(scenario, obs);
    fillMetrics(record, session);
    record.metrics.tokens = session.sessionId ? await tokensOf(name, session.sessionId) : null;
    record.errors = session.errors.map(redact);
    record.answer = redact(session.turns.at(-1)?.text ?? "");

    writeFileSync(join(artifacts, "frames.jsonl"), redact(session.frames.map((f) => JSON.stringify(f)).join("\n") + "\n"));
    if (notebookAfter !== null) writeFileSync(join(artifacts, "notebook.py"), notebookAfter);
    if (notebookRun) writeFileSync(join(artifacts, "notebook-run.txt"), redact(notebookRun.stderr));
  } catch (err) {
    // The harness or the workspace failed, not the model's answer: record it
    // as the failure so it shows in the table instead of aborting the batch.
    const message = redact((err as Error).message);
    record.errors.push(message);
    record.checks.push({ name: "harness", pass: false, detail: message });
    log(`harness error: ${message}`);
  } finally {
    writeFileSync(join(artifacts, "workspace.log"), redact(await logsOf(name).catch(() => "")));
    await removeContainer(name).catch(() => {});
  }

  record.failure = record.checks.find((c) => !c.pass)?.name ?? null;
  record.pass = record.checks.length > 0 && record.failure === null;
  return record;
}

/**
 * `marimo export html` executes every cell in dependency order, like opening
 * the notebook, and exits non-zero when any cell raises; `python notebook.py`
 * would stop at the first error and not say which cells never ran.
 */
async function runNotebook(name: string, scenario: Scenario): Promise<Observation["notebookRun"]> {
  const t = performance.now();
  const res = await execIn(
    name,
    ["marimo", "export", "html", scenario.notebook.path, "-o", "/tmp/atlas-evals-export.html"],
    scenario.notebook.run_timeout_s * 1000,
  );
  const output = [res.stdout, res.stderr].filter((s) => s.trim()).join("\n");
  return {
    exitCode: res.timedOut ? 124 : res.exitCode,
    stderr: res.timedOut ? `${output}\ntimed out after ${scenario.notebook.run_timeout_s} s` : output,
    seconds: (performance.now() - t) / 1000,
  };
}

// OpenCode keeps per-message token counts in its SQLite store; ACP does not
// report usage (yet). Best effort: null when the store's layout changes.
const TOKENS_PY = `
import json, os, sqlite3, sys
db = os.path.expanduser("~/.local/share/opencode/opencode.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
total = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
for (data,) in con.execute("select data from message where session_id = ?", (sys.argv[1],)):
    tokens = json.loads(data).get("tokens") or {}
    for k in total:
        total[k] += tokens.get(k) or 0
print(json.dumps(total))
`;

async function tokensOf(name: string, sessionId: string): Promise<Tokens | null> {
  const res = await execIn(name, ["python", "-c", TOKENS_PY, sessionId], 30_000);
  if (res.exitCode !== 0) return null;
  try {
    return JSON.parse(res.stdout) as Tokens;
  } catch {
    return null;
  }
}

function fillMetrics(record: RunRecord, session: SessionResult): void {
  const tools = toolStats(session.frames);
  record.metrics.turns = session.turns.map((t) => ({ stop_reason: t.stopReason, seconds: round(t.seconds) }));
  record.metrics.tool_calls = tools.calls;
  record.metrics.tool_calls_failed = tools.failed;
  record.metrics.tool_calls_by_kind = tools.byKind;
  record.metrics.permissions = session.permissions.map((p) => ({ title: p.title, kind: p.kind, option_id: p.optionId }));
}

function logFrame(f: Frame, log: (line: string) => void): void {
  if (f.type === "update" && f.update?.sessionUpdate === "tool_call") log(`tool ${f.update.kind ?? "?"}: ${f.update.title ?? ""}`);
  else if (f.type === "permission_request") log(`permission asked: ${f.toolCall?.title ?? "?"} (auto-approved)`);
  else if (f.type === "error") log(`error frame: ${f.message}`);
  else if (f.type === "turn_end") log(`turn_end ${f.stopReason}`);
}

function round(x: number): number {
  return Math.round(x * 10) / 10;
}
