// A scenario is one task a scientist would give the Workbench, with the
// deterministic checks that decide whether a run succeeded. Scenarios are YAML
// files in ../scenarios; the format is documented in ../README.md.

import { readFileSync } from "node:fs";
import { join } from "node:path";

export type PatternCheck = {
  name: string;
  why?: string;
  pattern: string;
  /** JavaScript RegExp flags; "i" when omitted. */
  flags?: string;
};

export type KeywordCheck = {
  name: string;
  /** Passes if the answer contains any of these (case- and accent-insensitive). */
  any: string[];
};

export type Scenario = {
  id: string;
  title: string;
  /** Sent one after the other, each once the previous turn has ended. */
  prompts: string[];
  /** Per prompt, from sending it to turn_end. */
  timeout_s: number;
  notebook: {
    path: string;
    must_change: boolean;
    must_run: boolean;
    run_timeout_s: number;
    checks: PatternCheck[];
  };
  answer: {
    /** Only "fr" is implemented: the Workbench speaks French. */
    language?: "fr";
    keywords: KeywordCheck[];
  };
};

export function loadScenario(dir: string, id: string): Scenario {
  const path = join(dir, `${id}.yaml`);
  let raw: unknown;
  try {
    raw = Bun.YAML.parse(readFileSync(path, "utf8"));
  } catch (err) {
    throw new Error(`cannot read scenario ${path}: ${(err as Error).message}`);
  }
  return validateScenario(raw, path);
}

/** Checks the shape and fills defaults, so a typo fails before any container starts. */
export function validateScenario(raw: unknown, where: string): Scenario {
  const fail = (msg: string): never => {
    throw new Error(`${where}: ${msg}`);
  };
  const s = raw as Record<string, any>;
  if (!s || typeof s !== "object") fail("not a mapping");
  if (typeof s.id !== "string" || !s.id) fail("`id` is required");
  if (!Array.isArray(s.prompts) || s.prompts.length === 0 || !s.prompts.every((p: unknown) => typeof p === "string" && p.trim()))
    fail("`prompts` must be a non-empty list of strings");

  const nb = s.notebook ?? {};
  const answer = s.answer ?? {};
  if (answer.language !== undefined && answer.language !== "fr") fail("`answer.language` supports only fr");

  const checks: PatternCheck[] = nb.checks ?? [];
  for (const c of checks) {
    if (typeof c.name !== "string" || typeof c.pattern !== "string") fail("each notebook check needs `name` and `pattern`");
    try {
      new RegExp(c.pattern, c.flags ?? "i");
    } catch (err) {
      fail(`notebook check ${c.name}: ${(err as Error).message}`);
    }
  }
  const keywords: KeywordCheck[] = answer.keywords ?? [];
  for (const k of keywords) {
    if (typeof k.name !== "string" || !Array.isArray(k.any) || k.any.length === 0) fail("each answer keyword needs `name` and a non-empty `any` list");
  }
  const names = [...checks.map((c) => c.name), ...keywords.map((k) => k.name)];
  const dup = names.find((n, i) => names.indexOf(n) !== i);
  if (dup) fail(`check name ${dup} is used twice`);

  return {
    id: s.id,
    title: typeof s.title === "string" ? s.title : s.id,
    prompts: s.prompts.map((p: string) => p.trim()),
    timeout_s: Number(s.timeout_s ?? 600),
    notebook: {
      path: nb.path ?? "/workspace/notebook.py",
      must_change: nb.must_change ?? true,
      must_run: nb.must_run ?? true,
      run_timeout_s: Number(nb.run_timeout_s ?? 300),
      checks,
    },
    answer: { language: answer.language, keywords },
  };
}
