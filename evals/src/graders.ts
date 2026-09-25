// Deterministic graders: pure functions from what a run produced to a list of
// named pass/fail checks. No LLM judge — a check either matches or it does not,
// so the same run always gets the same grade and a failure says exactly why.

import type { Scenario } from "./scenario";
import type { Turn } from "./session";

export type Check = { name: string; pass: boolean; detail?: string };

export type Observation = {
  turns: Turn[];
  errors: string[];
  notebookBefore: string | null;
  notebookAfter: string | null;
  /** `marimo export html` of the final notebook; null when it was not run. */
  notebookRun: { exitCode: number; stderr: string; seconds: number } | null;
};

export function grade(scenario: Scenario, obs: Observation): Check[] {
  const checks: Check[] = [];
  const last = obs.turns.at(-1);

  // 1. The agent finished every prompt by itself, and nothing reported an error.
  const allEnded = obs.turns.length === scenario.prompts.length && obs.turns.every((t) => t.stopReason === "end_turn");
  checks.push({
    name: "turn_end",
    pass: allEnded,
    detail: allEnded ? undefined : `stop reasons: ${obs.turns.map((t) => t.stopReason).join(", ") || "none"} (${obs.turns.length}/${scenario.prompts.length} turns)`,
  });
  checks.push({
    name: "no_errors",
    pass: obs.errors.length === 0,
    detail: obs.errors.length ? clip(obs.errors.join(" | ")) : undefined,
  });

  // 2. The notebook: written, and it runs top to bottom.
  const nb = scenario.notebook;
  const after = obs.notebookAfter;
  if (nb.must_change) {
    const changed = after !== null && after !== obs.notebookBefore;
    checks.push({ name: "notebook_changed", pass: changed, detail: after === null ? "notebook missing" : changed ? undefined : "unchanged" });
  }
  if (nb.must_run) {
    const run = obs.notebookRun;
    const pass = run !== null && run.exitCode === 0;
    checks.push({
      name: "notebook_runs",
      pass,
      detail: pass ? undefined : run === null ? "not run (no notebook)" : `exit ${run.exitCode}: ${clip(lastLines(run.stderr, 6))}`,
    });
  }
  for (const c of nb.checks) {
    const pass = after !== null && new RegExp(c.pattern, c.flags ?? "i").test(after);
    checks.push({ name: `nb:${c.name}`, pass, detail: pass ? undefined : `no match for /${c.pattern}/` });
  }

  // 3. The answer the scientist reads in the chat (the last turn's text).
  const answer = last?.text ?? "";
  if (scenario.answer.language === "fr") {
    const lang = frenchScore(answer);
    checks.push({
      name: "answer_french",
      pass: lang.french,
      detail: lang.french ? undefined : `${lang.fr} French vs ${lang.en} English stopwords`,
    });
  }
  const haystack = normalize(answer);
  for (const k of scenario.answer.keywords) {
    const pass = k.any.some((word) => haystack.includes(normalize(word)));
    checks.push({ name: `answer:${k.name}`, pass, detail: pass ? undefined : `none of ${k.any.join(" / ")}` });
  }
  return checks;
}

/** Lowercase, no accents, straight apostrophes: "Pathogène" matches "pathogene". */
export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[‘’ʼ]/g, "'")
    .toLowerCase();
}

// Frequent function words that are unambiguous between the two languages. A
// stopword count is crude but deterministic and good enough to catch a model
// that ignores the "reply in French" instruction.
const FR = new Set("le la les des du une est et dans pour sur par avec qui que pas sont ce cette il elle au aux mais ou donc".split(" "));
const EN = new Set("the is and of in to with that this for are on it be by an which was not from its has have".split(" "));

export function frenchScore(text: string): { fr: number; en: number; french: boolean } {
  let fr = 0;
  let en = 0;
  for (const word of normalize(text).split(/[^a-z]+/)) {
    if (FR.has(word)) fr++;
    else if (EN.has(word)) en++;
  }
  return { fr, en, french: fr >= 10 && fr > 2 * en };
}

function lastLines(text: string, n: number): string {
  return text.trim().split("\n").slice(-n).join(" / ");
}

function clip(text: string, max = 400): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
