import { describe, expect, test } from "bun:test";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { frenchScore, grade, normalize, otherNotebooksChanged, type Observation } from "../src/graders";
import { median, summarize, type RunRecord } from "../src/report";
import { loadScenario, validateScenario } from "../src/scenario";
import { pickAllow, skillsLoaded, toolCallTexts, toolStats } from "../src/session";

const scenario = loadScenario(join(import.meta.dir, "..", "scenarios"), "tp53-r175h");

const GOOD_NOTEBOOK = `
import marimo
app = marimo.App()

@app.cell
def _():
    import atlas_viewers as av
    import requests
    entry = requests.get("https://rest.uniprot.org/uniprotkb/P04637.json").json()
    return av, entry

@app.cell
def _(av):
    av.structure("https://alphafold.ebi.ac.uk/files/AF-P04637-F1-model_v4.cif", highlight=[175], labels={175: "R175H"})
    return
`;

const GOOD_ANSWER = `Le variant p.R175H se situe dans le domaine de liaison à l'ADN de la protéine p53,
près du site de fixation du zinc. Il est classé pathogène dans ClinVar, notamment pour le syndrome de
Li-Fraumeni. La littérature le décrit comme un point chaud et un mutant avec gain de fonction : il est
fréquent dans les tumeurs et les souris qui le portent ont des cancers plus invasifs. Les sources sont
dans le notebook, avec les liens vers les articles et les bases de données.`;

const ACTIVE = "tp53-r175h/notebooks/analyse.py";
const OTHER = "tp53-r175h/notebooks/brouillon.py";

/** A run in a project with two notebooks, where the agent rewrote the active one. */
function observation(over: Partial<Observation> & { notebookAfter?: string | null } = {}): Observation {
  const { notebookAfter = GOOD_NOTEBOOK, ...rest } = over;
  const after: Record<string, string> = { [OTHER]: "draft" };
  if (notebookAfter !== null) after[ACTIVE] = notebookAfter;
  return {
    turns: [{ prompt: "p", stopReason: "end_turn", text: GOOD_ANSWER, seconds: 12 }],
    errors: [],
    activeNotebook: ACTIVE,
    notebooksBefore: { [ACTIVE]: "welcome", [OTHER]: "draft" },
    notebooksAfter: after,
    contextBefore: "# tp53-r175h\n",
    contextAfter: "# tp53-r175h\n",
    notebookRun: { exitCode: 0, stderr: "", seconds: 3 },
    toolCalls: [],
    ...rest,
  };
}

const failed = (obs: Observation) => grade(scenario, obs).filter((c) => !c.pass).map((c) => c.name);

describe("grade", () => {
  test("tools checks pass when any tool call matches, and are named tool:<name>", () => {
    const hub = loadScenario(join(import.meta.dir, "..", "scenarios"), "rbd-ace2-hub");
    const names = (obs: Observation) => grade(hub, obs).filter((c) => c.name.startsWith("tool:"));
    const none = names(observation({ toolCalls: ['bash\n{"command":"python -c \'import requests\'"}'] }));
    expect(none.map((c) => [c.name, c.pass])).toEqual([["tool:hub_search", false]]);
    const shell = names(observation({ toolCalls: ["read", 'bash\n{"command":"python -m atlas_hub search protein data bank --json"}'] }));
    expect(shell.every((c) => c.pass)).toBe(true);
    const cell = names(observation({ toolCalls: ['write\n{"content":"found = hub.search(\\"protein data bank\\")"}'] }));
    expect(cell.every((c) => c.pass)).toBe(true);
  });

  test("a good run passes every check", () => {
    expect(failed(observation())).toEqual([]);
  });

  test("a cancelled or failed turn fails turn_end", () => {
    expect(failed(observation({ turns: [{ prompt: "p", stopReason: "timeout", text: GOOD_ANSWER, seconds: 900 }] }))).toContain("turn_end");
    expect(failed(observation({ turns: [] }))).toContain("turn_end");
  });

  test("error frames fail no_errors", () => {
    expect(failed(observation({ errors: ["agent crashed"] }))).toEqual(["no_errors"]);
  });

  test("an untouched or missing notebook fails, and is not run", () => {
    expect(failed(observation({ notebookAfter: "welcome" }))).toContain("notebook_changed");
    const missing = failed(observation({ notebookAfter: null, notebookRun: null }));
    expect(missing).toContain("notebook_changed");
    expect(missing).toContain("notebook_runs");
  });

  test("writing another notebook, or a new one, fails wrote_active_notebook", () => {
    const base = observation();
    const other = grade(scenario, { ...base, notebooksAfter: { ...base.notebooksAfter, [OTHER]: GOOD_NOTEBOOK } });
    expect(other.filter((c) => !c.pass).map((c) => c.name)).toEqual(["wrote_active_notebook"]);
    expect(other.find((c) => c.name === "wrote_active_notebook")!.detail).toBe(`also wrote ${OTHER}`);

    // The single notebook of the old contract, written instead of the active one.
    const legacy = grade(scenario, { ...base, notebooksAfter: { ...base.notebooksBefore, "notebook.py": GOOD_NOTEBOOK } });
    const check = legacy.find((c) => c.name === "wrote_active_notebook")!;
    expect(check.pass).toBe(false);
    expect(check.detail).toBe(`${ACTIVE} not written; also wrote notebook.py`);
  });

  test("editing PROJET.md unasked fails project_context_untouched", () => {
    expect(failed(observation({ contextAfter: "# tp53-r175h\n\n## Question de recherche\nTP53" }))).toEqual(["project_context_untouched"]);
  });

  test("otherNotebooksChanged sees created, changed and removed notebooks, not the active one", () => {
    expect(
      otherNotebooksChanged({
        activeNotebook: "p/notebooks/a.py",
        notebooksBefore: { "p/notebooks/a.py": "1", "p/notebooks/b.py": "1", "p/notebooks/c.py": "1" },
        notebooksAfter: { "p/notebooks/a.py": "2", "p/notebooks/b.py": "2", "p/notebooks/d.py": "1" },
      }),
    ).toEqual(["p/notebooks/b.py", "p/notebooks/c.py", "p/notebooks/d.py"]);
  });

  test("a notebook whose cells raise fails notebook_runs with the error in the detail", () => {
    const checks = grade(scenario, observation({ notebookRun: { exitCode: 1, stderr: "ValueError: boom\nError: some cells failed", seconds: 2 } }));
    const run = checks.find((c) => c.name === "notebook_runs")!;
    expect(run.pass).toBe(false);
    expect(run.detail).toContain("ValueError: boom");
  });

  test("notebook content checks are the scenario's regexes", () => {
    const noViewers = GOOD_NOTEBOOK.replace("import atlas_viewers as av", "import pandas as pd").replace(/av\.structure[^\n]*/, "pd.DataFrame()");
    expect(failed(observation({ notebookAfter: noViewers }))).toEqual(["nb:uses_atlas_viewers", "nb:structure_viewer", "nb:highlights_175"]);
  });

  test("the residue may be highlighted through a name bound to it", () => {
    const named = GOOD_NOTEBOOK.replace("highlight=[175], labels={175:", "highlight=[POSITION], labels={POSITION:").replace("    import requests", "    import requests\n    POSITION = 175");
    expect(failed(observation({ notebookAfter: named }))).toEqual([]);
    expect(failed(observation({ notebookAfter: named.replace("POSITION = 175", "POSITION = 176") }))).toEqual(["nb:highlights_175"]);
  });

  test("an English answer fails the language check", () => {
    const english = "The variant is in the DNA-binding domain of the protein. It is pathogenic in ClinVar and is linked to Li-Fraumeni syndrome, with zinc loss. This is from the literature and it has been described by many.";
    expect(failed(observation({ turns: [{ prompt: "p", stopReason: "end_turn", text: english, seconds: 1 }] }))).toContain("answer_french");
  });

  test("keywords ignore case and accents", () => {
    const flat = GOOD_ANSWER.toUpperCase().normalize("NFD").replace(/\p{M}/gu, "");
    expect(failed(observation({ turns: [{ prompt: "p", stopReason: "end_turn", text: flat, seconds: 1 }] }))).toEqual([]);
  });
});

test("normalize folds accents, case and curly apostrophes", () => {
  expect(normalize("Liaison à l’ADN — Pathogène")).toBe("liaison a l'adn - pathogene");
});

test("frenchScore needs enough French words", () => {
  expect(frenchScore(GOOD_ANSWER).french).toBe(true);
  expect(frenchScore("Oui.").french).toBe(false);
});

test("validateScenario rejects a bad regex and duplicate names", () => {
  expect(() => validateScenario({ id: "x", prompts: ["p"], notebook: { checks: [{ name: "a", pattern: "(" }] } }, "x")).toThrow(/notebook check a/);
  expect(() =>
    validateScenario({ id: "x", prompts: ["p"], notebook: { checks: [{ name: "a", pattern: "a" }] }, answer: { keywords: [{ name: "a", any: ["a"] }] } }, "x"),
  ).toThrow(/used twice/);
  expect(() => validateScenario({ id: "x", prompts: [] }, "x")).toThrow(/prompts/);
});

test("every scenario in scenarios/ loads, and its id is its file name", () => {
  const dir = join(import.meta.dir, "..", "scenarios");
  const ids = readdirSync(dir).filter((f) => f.endsWith(".yaml")).map((f) => f.replace(/\.yaml$/, ""));
  expect(ids.length).toBeGreaterThan(0);
  for (const id of ids) expect(loadScenario(dir, id).id).toBe(id);
});

test("validateScenario takes an optional notebook name and rejects the old fixed path", () => {
  expect(validateScenario({ id: "x", prompts: ["p"] }, "x").notebook.name).toBeUndefined();
  expect(validateScenario({ id: "x", prompts: ["p"], notebook: { name: " Structure BRCA1 " } }, "x").notebook.name).toBe("Structure BRCA1");
  expect(() => validateScenario({ id: "x", prompts: ["p"], notebook: { path: "/workspace/notebook.py" } }, "x")).toThrow(/notebook\.path/);
  expect(() => validateScenario({ id: "x", prompts: ["p"], notebook: { name: "" } }, "x")).toThrow(/notebook\.name/);
});

test("skillsLoaded reads OpenCode's skill tool calls", () => {
  const u = (update: object) => ({ type: "update", update });
  expect(
    skillsLoaded([
      u({ sessionUpdate: "tool_call", toolCallId: "1", title: "skill", rawInput: {} }),
      u({ sessionUpdate: "tool_call_update", toolCallId: "1", title: "skill", rawInput: { name: "atlas-viewers" } }),
      u({ sessionUpdate: "tool_call_update", toolCallId: "1", title: "Loaded skill: atlas-viewers" }),
      u({ sessionUpdate: "tool_call_update", toolCallId: "2", title: "Loaded skill: clinical-trials" }),
      u({ sessionUpdate: "tool_call", toolCallId: "3", title: "read", rawInput: { filePath: "skill.md" } }),
    ]),
  ).toEqual(["atlas-viewers", "clinical-trials"]);
});

test("pickAllow prefers allow_once", () => {
  expect(pickAllow([{ optionId: "always", kind: "allow_always" }, { optionId: "once", kind: "allow_once" }, { optionId: "no", kind: "reject_once" }])).toBe("once");
  expect(pickAllow([])).toBe("cancelled");
});

test("toolStats counts calls by id and keeps the kind from the first frame", () => {
  const u = (update: object) => ({ type: "update", update });
  const stats = toolStats([
    u({ sessionUpdate: "tool_call", toolCallId: "1", kind: "read", status: "pending" }),
    u({ sessionUpdate: "tool_call_update", toolCallId: "1", status: "completed" }),
    u({ sessionUpdate: "tool_call", toolCallId: "2", kind: "execute", status: "pending" }),
    u({ sessionUpdate: "tool_call_update", toolCallId: "2", status: "failed" }),
    u({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "x" } }),
  ]);
  expect(stats).toEqual({ calls: 2, failed: 1, byKind: { read: 1, execute: 1 } });
});

test("toolCallTexts keeps every title and input of a call, one string per call", () => {
  const u = (update: object) => ({ type: "update", update });
  const texts = toolCallTexts([
    u({ sessionUpdate: "tool_call", toolCallId: "1", title: "bash", kind: "execute", rawInput: {} }),
    u({ sessionUpdate: "tool_call_update", toolCallId: "1", rawInput: { command: "python -m atlas_hub search sars" } }),
    u({ sessionUpdate: "tool_call", toolCallId: "2", title: "read" }),
    u({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "x" } }),
  ]);
  expect(texts).toEqual(['bash\n{}\n{"command":"python -m atlas_hub search sars"}', "read"]);
});

test("summarize ranks models by pass rate", () => {
  const rec = (model: string, pass: boolean, wall: number): RunRecord => ({
    run_id: `${model}-${wall}`,
    scenario: "s",
    model,
    base_url: "http://x/v1",
    attempt: 1,
    started_at: "",
    pass,
    failure: pass ? null : "notebook_runs",
    checks: [{ name: "notebook_runs", pass }],
    metrics: { startup_s: 5, wall_s: wall, turns: [], tool_calls: 3, tool_calls_failed: 0, tool_calls_by_kind: {}, permissions: [], skills: ["atlas-viewers"], tokens: null },
    errors: [],
    answer: "",
    artifacts: "",
  });
  const md = summarize([rec("weak", false, 10), rec("strong", true, 20), rec("strong", true, 40)], "s");
  const lines = md.split("\n");
  expect(lines[4]).toStartWith("| strong | 2/2 | 100 % | 30 s |");
  expect(lines[4]).toContain("| atlas-viewers (2/2) |");
  expect(lines[5]).toContain("notebook_runs (1/1)");
  expect(median([3, null, 1, 2])).toBe(2);
});

describe("normalize", () => {
  test("typographic hyphens and spaces match their plain forms", () => {
    // Sonnet wrote "Li‑Fraumeni" with U+2011 and lost the keyword.
    expect(normalize("syndrome de Li‑Fraumeni")).toContain(normalize("Li-Fraumeni"));
    expect(normalize("TP53 p.R175H")).toBe("tp53 p.r175h");
  });
});
