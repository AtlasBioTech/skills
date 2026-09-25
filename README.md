# Atlas skills

Agent skills, plugins and evals for bio/pharma work with the
[Atlas hub](https://demoatlas.online).

The skills teach an AI coding agent how to do domain work well: query public
databases (UniProt, AlphaFold DB, ClinVar, Europe PMC…), set up a reproducible
scientific environment, write a marimo notebook that uses the Atlas viewers,
and publish results to the hub with the `atlas` CLI.

They follow the open [Agent Skills](https://agentskills.io) format
(`SKILL.md`), so the same skill works in the Atlas Workbench, Claude Code,
Codex, OpenCode and other agents that support it.

## Layout

| Folder | What |
|---|---|
| [`skills/`](skills/) | One folder per skill, each with a `SKILL.md` |
| [`evals/`](evals/) | Scenarios and graders that measure whether a skill actually helps, and which models can follow them |

Plugin packaging (a Claude Code plugin marketplace, a Codex plugin, an
OpenCode config) will be added here once the skills settle.

## Licence

Apache-2.0. The skills call the `atlas` CLI from
[`hub_sdk`](https://github.com/AtlasBioTech/hub_sdk).
