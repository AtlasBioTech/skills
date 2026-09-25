// Turns run records into the Markdown summary: one row per model, then which
// checks each model passes, so a ranking also says what to fix.

import type { Check } from "./graders";

export type Tokens = { input: number; output: number; reasoning: number; total: number };

export type RunRecord = {
  run_id: string;
  scenario: string;
  model: string;
  base_url: string;
  attempt: number;
  started_at: string;
  pass: boolean;
  /** First failed check, or the harness error that stopped the run. */
  failure: string | null;
  checks: Check[];
  metrics: {
    startup_s: number | null;
    wall_s: number | null;
    turns: { stop_reason: string; seconds: number }[];
    tool_calls: number;
    tool_calls_failed: number;
    tool_calls_by_kind: Record<string, number>;
    permissions: { title: string; kind: string; option_id: string }[];
    tokens: Tokens | null;
  };
  errors: string[];
  answer: string;
  artifacts: string;
};

export function summarize(records: RunRecord[], scenarioId: string): string {
  const models = [...new Set(records.map((r) => r.model))];
  const byModel = (m: string) => records.filter((r) => r.model === m);

  const rows = models
    .map((model) => {
      const rs = byModel(model);
      const passed = rs.filter((r) => r.pass).length;
      return {
        model,
        rate: passed / rs.length,
        cells: [
          model,
          `${passed}/${rs.length}`,
          `${Math.round((100 * passed) / rs.length)} %`,
          fmt(median(rs.map((r) => r.metrics.wall_s)), " s"),
          fmt(median(rs.map((r) => r.metrics.tool_calls))),
          fmt(median(rs.map((r) => r.metrics.tokens?.total ?? null))),
          mainFailure(rs),
        ],
      };
    })
    .sort((a, b) => b.rate - a.rate);

  const out = [
    `## ${scenarioId} — ${records.length} runs`,
    "",
    table(["model", "passed", "pass rate", "median time", "median tool calls", "median tokens", "main failure"], rows.map((r) => r.cells)),
  ];

  // Per-check pass counts: shows how close a failing model is.
  const checkNames = [...new Set(records.flatMap((r) => r.checks.map((c) => c.name)))];
  if (checkNames.length) {
    const ordered = rows.map((r) => r.model);
    out.push(
      "",
      "### Checks passed, by model",
      "",
      table(
        ["check", ...ordered],
        checkNames.map((name) => [
          name,
          ...ordered.map((m) => {
            const rs = byModel(m);
            return `${rs.filter((r) => r.checks.some((c) => c.name === name && c.pass)).length}/${rs.length}`;
          }),
        ]),
      ),
    );
  }
  return out.join("\n") + "\n";
}

function mainFailure(rs: RunRecord[]): string {
  const counts = new Map<string, number>();
  for (const r of rs) if (r.failure) counts.set(r.failure, (counts.get(r.failure) ?? 0) + 1);
  const top = [...counts].sort((a, b) => b[1] - a[1])[0];
  return top ? `${top[0]} (${top[1]}/${rs.length})` : "—";
}

export function median(values: (number | null)[]): number | null {
  const xs = values.filter((v): v is number => v !== null).sort((a, b) => a - b);
  if (xs.length === 0) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid]! : (xs[mid - 1]! + xs[mid]!) / 2;
}

function fmt(v: number | null, unit = ""): string {
  if (v === null) return "—";
  return `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`;
}

function table(header: string[], rows: string[][]): string {
  const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\n/g, " ");
  return [
    `| ${header.map(esc).join(" | ")} |`,
    `|${header.map(() => "---").join("|")}|`,
    ...rows.map((r) => `| ${r.map(esc).join(" | ")} |`),
  ].join("\n");
}
