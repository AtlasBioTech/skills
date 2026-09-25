import { describe, expect, test } from "bun:test";
import { join } from "node:path";
import { frenchScore, grade, normalize, type Observation } from "../src/graders";
import { median, summarize, type RunRecord } from "../src/report";
import { loadScenario, validateScenario } from "../src/scenario";
import { pickAllow, toolStats } from "../src/session";

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

function observation(over: Partial<Observation> = {}): Observation {
  return {
    turns: [{ prompt: "p", stopReason: "end_turn", text: GOOD_ANSWER, seconds: 12 }],
    errors: [],
    notebookBefore: "welcome",
    notebookAfter: GOOD_NOTEBOOK,
    notebookRun: { exitCode: 0, stderr: "", seconds: 3 },
    ...over,
  };
}

const failed = (obs: Observation) => grade(scenario, obs).filter((c) => !c.pass).map((c) => c.name);

describe("grade", () => {
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
  expect(normalize("Liaison à l’ADN — Pathogène")).toBe("liaison a l'adn — pathogene");
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
    metrics: { startup_s: 5, wall_s: wall, turns: [], tool_calls: 3, tool_calls_failed: 0, tool_calls_by_kind: {}, permissions: [], tokens: null },
    errors: [],
    answer: "",
    artifacts: "",
  });
  const md = summarize([rec("weak", false, 10), rec("strong", true, 20), rec("strong", true, 40)], "s");
  const lines = md.split("\n");
  expect(lines[4]).toStartWith("| strong | 2/2 | 100 % | 30 s |");
  expect(lines[5]).toContain("notebook_runs (1/1)");
  expect(median([3, null, 1, 2])).toBe(2);
});
