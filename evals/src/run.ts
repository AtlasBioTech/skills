// One run: a fresh workspace for one model, the scenario's prompts, the
// graders, the teardown. Everything the run produced is kept next to its record
// so a failure can be read without re-running it.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { execIn, logsOf, removeContainer, startWorkspace, waitHealthy, type WorkspaceSpec } from "./docker";
import { grade, otherNotebooksChanged, type Observation } from "./graders";
import type { RunRecord, Tokens } from "./report";
import type { Scenario } from "./scenario";
import { runSession, skillsLoaded, toolStats, type Frame, type SessionResult } from "./session";

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
      skills: [],
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

    let notebooksBefore: Record<string, string> = {};
    const t1 = performance.now();
    const session = await runSession({
      url: `ws://${name}:${cfg.bridgePort}/ws`,
      project: scenario.id,
      notebook: scenario.notebook.name,
      prompts: scenario.prompts,
      timeoutMs: scenario.timeout_s * 1000,
      onOpen: async (opened) => {
        log(`opened ${opened.project}/${opened.notebook}, conversation ${opened.conversation}`);
        notebooksBefore = await notebooksIn(name);
      },
      onFrame: (f) => logFrame(f, log),
    });
    record.metrics.wall_s = round((performance.now() - t1) / 1000);

    const { project, conversation, notebook } = session.opened;
    const activeNotebook = `${project}/${notebook}`;
    record.project = project;
    record.notebook = notebook;
    const notebooksAfter = await notebooksIn(name);
    const notebookAfter = notebooksAfter[activeNotebook] ?? null;
    const notebookRun = scenario.notebook.must_run && notebookAfter !== null ? await runNotebook(name, activeNotebook, scenario) : null;
    if (notebookRun) log(`notebook ${notebookRun.exitCode === 0 ? "runs" : `fails (exit ${notebookRun.exitCode})`} in ${round(notebookRun.seconds)} s`);

    const obs: Observation = { turns: session.turns, errors: session.errors, activeNotebook, notebooksBefore, notebooksAfter, notebookRun };
    record.checks = grade(scenario, obs);
    fillMetrics(record, session);
    record.metrics.tokens = await tokensOf(name, project, conversation);
    record.errors = session.errors.map(redact);
    record.answer = redact(session.turns.at(-1)?.text ?? "");

    writeFileSync(join(artifacts, "frames.jsonl"), redact(session.frames.map((f) => JSON.stringify(f)).join("\n") + "\n"));
    if (notebookAfter !== null) writeFileSync(join(artifacts, "notebook.py"), notebookAfter);
    // What the agent wrote besides the active notebook, to read a failed wrote_active_notebook.
    for (const path of otherNotebooksChanged(obs)) {
      const content = notebooksAfter[path];
      if (content !== undefined) writeFileSync(join(artifacts, `other-${path.replace(/[^A-Za-z0-9._-]+/g, "_")}`), content);
    }
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
async function runNotebook(name: string, notebook: string, scenario: Scenario): Promise<Observation["notebookRun"]> {
  const t = performance.now();
  const res = await execIn(
    name,
    ["marimo", "export", "html", `/workspace/${notebook}`, "-o", "/tmp/atlas-evals-export.html"],
    scenario.notebook.run_timeout_s * 1000,
  );
  const output = [res.stdout, res.stderr].filter((s) => s.trim()).join("\n");
  return {
    exitCode: res.timedOut ? 124 : res.exitCode,
    stderr: res.timedOut ? `${output}\ntimed out after ${scenario.notebook.run_timeout_s} s` : output,
    seconds: (performance.now() - t) / 1000,
  };
}

// Every notebook of the workspace, to tell which ones the agent wrote: the
// .py files in a notebooks/ folder, and any other marimo file (the agent may
// write one at the project's root or at the workspace's). Hidden folders
// (skills, .atlas state) are not the scientist's notebooks.
const NOTEBOOKS_PY = `
import json, os
root = "/workspace"
found = {}
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
    for f in filenames:
        if not f.endswith(".py"):
            continue
        path = os.path.join(dirpath, f)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if os.path.basename(dirpath) == "notebooks" or "marimo.App(" in text:
            found[os.path.relpath(path, root)] = text
print(json.dumps(found))
`;

async function notebooksIn(name: string): Promise<Record<string, string>> {
  const res = await execIn(name, ["python", "-c", NOTEBOOKS_PY], 30_000);
  if (res.exitCode !== 0) throw new Error(`listing the notebooks failed: ${res.stderr.trim().slice(-300)}`);
  return JSON.parse(res.stdout) as Record<string, string>;
}

// OpenCode keeps per-message token counts in its SQLite store, under the
// workspace's XDG_DATA_HOME (docs/contracts.md §3); ACP does not report usage
// (yet). The conversation's metadata names its ACP session. Best effort: null
// when either layout changes. Cache reads are counted in "input" at full
// weight, so this is not a cost.
const TOKENS_PY = `
import json, os, sqlite3, sys
project, conversation = sys.argv[1], sys.argv[2]
meta = json.load(open(os.path.join("/workspace", project, ".atlas", "conversations", conversation + ".json")))
db = next(p for p in ("/workspace/.atlas/home/data/opencode/opencode.db", os.path.expanduser("~/.local/share/opencode/opencode.db")) if os.path.exists(p))
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
total = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
for (data,) in con.execute("select data from message where session_id = ?", (meta["sessionId"],)):
    tokens = json.loads(data).get("tokens") or {}
    for k in total:
        total[k] += tokens.get(k) or 0
print(json.dumps(total))
`;

async function tokensOf(name: string, project: string, conversation: string): Promise<Tokens | null> {
  const res = await execIn(name, ["python", "-c", TOKENS_PY, project, conversation], 30_000);
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
  record.metrics.skills = skillsLoaded(session.frames);
}

function logFrame(f: Frame, log: (line: string) => void): void {
  if (f.type === "update" && f.update?.sessionUpdate === "tool_call") log(`tool ${f.update.kind ?? "?"}: ${f.update.title ?? ""}`);
  else if (f.type === "permission_request") log(`permission asked: ${f.toolCall?.title ?? "?"} (auto-approved)`);
  else if (f.type === "update" && f.update?.title === "skill" && f.update?.rawInput?.name) log(`skill loaded: ${f.update.rawInput.name}`);
  else if (f.type === "refused") log(`refused: ${f.message}`);
  else if (f.type === "error") log(`error frame: ${f.message}`);
  else if (f.type === "turn_end") log(`turn_end ${f.stopReason}`);
}

function round(x: number): number {
  return Math.round(x * 10) / 10;
}
