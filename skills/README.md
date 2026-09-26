# Skills

One folder per skill:

```
skills/<skill-name>/
  SKILL.md        # name + description frontmatter, then the instructions
  scripts/        # optional helpers the skill tells the agent to run
  references/     # optional longer docs the agent reads on demand
```

| Skill | What |
|---|---|
| [`atlas-viewers`](atlas-viewers/SKILL.md) | Show a protein's 3D structure, its variants and result tables in a marimo notebook with `atlas_viewers`, fetching UniProt, AlphaFold DB, ClinVar and Europe PMC in the notebook |

Keep each `SKILL.md` short and specific; put long material in `references/`.
A skill without an eval in `../evals/` is a guess.
