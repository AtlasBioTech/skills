# Evals

Each eval is a scenario: a prompt a scientist would type and deterministic
checks on the outcome (the agent finished, the notebook runs, it shows the
right thing, the answer is in French and states the key facts).

Two uses:

1. **Which model can do it?** Run the scenario against each model behind an
   OpenAI-compatible endpoint, driven by OpenCode inside the real Atlas
   workspace, before we promise it to anyone. This is what the runner below
   does today.
2. **Does a skill help?** Run the scenario with and without it (later).

Public benchmarks (LAB-Bench, BixBench…) come later.

## How a run works

For each model × run, the runner:

1. starts a **fresh workspace container** (the Workbench `workspace` image:
   OpenCode + marimo + the ACP bridge) on a private docker network, with
   `ATLAS_LLM_BASE_URL`, `ATLAS_LLM_API_KEY` and `ATLAS_LLM_MODEL` set, limited
   to 2 CPUs and 3 GB;
2. waits for the bridge's `GET /healthz` (200 once OpenCode has a session);
3. sends each prompt over the session WebSocket (workbench
   `docs/contracts.md` §1) and keeps every frame until `turn_end`; permission
   requests are **approved** (`allow_once`) and recorded; a turn that exceeds
   the scenario's timeout is cancelled, then graded as it stands;
4. reads `/workspace/notebook.py` and executes it with `marimo export html`
   inside the container;
5. grades, saves the artifacts, removes the container.

Runs are ordered attempt by attempt (model A #1, model B #1, model A #2…) so a
slow patch on the endpoint penalises every model alike.

**Why Bun/TypeScript:** the bridge and its WebSocket client are TypeScript on
Bun, so the runner speaks the same frames with the same idioms, has no runtime
dependencies (WebSocket, YAML and `fetch` are built into Bun), and ships as a
small image with the docker CLI.

## Run it

Build the runner once (from the repository root):

```sh
docker build -t atlas-evals evals/
docker network create atlas-evals-net     # once; the runner and the workspaces share it
mkdir -p evals/runs                        # else docker creates it owned by root
```

The runner starts workspace containers through the host's docker socket, so it
is mounted in; `-u`/`--group-add` keep the files it writes in `evals/runs/`
owned by you.

### Against Scaleway Generative APIs

```sh
export SCW_SECRET_KEY=…     # the key stays in your shell's environment

# what models are offered
docker run --rm -e SCW_SECRET_KEY atlas-evals list-models

# rank the chat models picked from that list on the demo scenario, 5 runs each
docker run --rm --network atlas-evals-net \
  -v /var/run/docker.sock:/var/run/docker.sock --group-add "$(stat -c %g /var/run/docker.sock)" \
  -u "$(id -u):$(id -g)" -v "$PWD/evals/runs:/evals/runs" -e SCW_SECRET_KEY \
  atlas-evals run --scenario tp53-r175h --runs 5 --image atlas-workspace --models <model-a>,<model-b>,<model-c>
```

`list-models` also lists embedding and audio models; pass only chat models
that support tool calls (OpenCode cannot work without them).

The default base URL is `https://api.scaleway.ai/v1` (pass `--base-url` for a
project-scoped URL or another gateway). `-e SCW_SECRET_KEY` without a value
copies it from your shell; the runner hands it to each workspace the same way
(`docker run -e ATLAS_LLM_API_KEY`), so it is never on a command line, and it
is replaced by `[REDACTED]` in anything the runner writes. `ATLAS_LLM_API_KEY`
works too.

Five runs × N models at ~2–5 min a run is long: `--concurrency 2` runs two
workspaces at a time (each takes up to 2 CPUs / 3 GB).

### Against the scripted mock model (no key)

The Workbench's `dev/mock-llm` plays the TP53 scenario (model id `atlas-demo`):

```sh
docker run -d --name atlas-evals-mockllm --network atlas-evals-net atlas-mock-llm
docker run --rm --network atlas-evals-net \
  -v /var/run/docker.sock:/var/run/docker.sock --group-add "$(stat -c %g /var/run/docker.sock)" \
  -u "$(id -u):$(id -g)" -v "$PWD/evals/runs:/evals/runs" \
  atlas-evals run --scenario tp53-r175h --models atlas-demo --runs 3 \
  --base-url http://atlas-evals-mockllm:14000/v1 --image atlas-workspace
```

### Options

`atlas-evals run --help` lists them: `--base-url`, `--provider`, `--image`,
`--network`, `--prefix` (container names, default `atlas-evals`),
`--concurrency`, `--cpus`, `--memory`, `--startup-timeout`, `--out`. Ctrl-C
removes the batch's workspaces.

## Output

`evals/runs/<UTC timestamp>/` (gitignored):

| File | |
|---|---|
| `summary.md` | the ranking (also printed): model × pass rate × median time × median tool calls × median tokens × main failure, then how many runs pass each check |
| `runs.jsonl` | one record per run: every check with its failure detail, metrics (startup and turn times, tool calls by kind, failed tool calls, permissions granted, tokens), errors, the final answer |
| `<run>/frames.jsonl` | every bridge frame of the session |
| `<run>/notebook.py` | the notebook the agent left |
| `<run>/notebook-run.txt` | output of `marimo export html` (the traceback when a cell fails) |
| `<run>/workspace.log` | the container's last 300 log lines |

`atlas-evals summarize evals/runs/<timestamp>` re-prints the summary. A run
**passes** when every check passes; "main failure" is the most frequent first
failed check.

## Graders

All deterministic (no LLM judge), in [`src/graders.ts`](src/graders.ts):

| Check | Passes when |
|---|---|
| `turn_end` | every prompt's turn ended with `stopReason: "end_turn"` (not `timeout`, `cancelled`, `error`, `max_tokens`, a disconnect…) |
| `no_errors` | the bridge sent no `error` frame and nothing timed out |
| `notebook_changed` | the notebook exists and differs from the one before the first prompt |
| `notebook_runs` | `marimo export html` of the notebook exits 0 within `run_timeout_s`, i.e. every cell ran without raising (it executes all cells in dependency order, like opening the notebook; the detail quotes the error) |
| `nb:<name>` | the notebook matches the scenario's regex |
| `answer_french` | the last turn's text is French: ≥ 10 French function words and more than twice as many as English ones |
| `answer:<name>` | the last turn's text contains one of the scenario's keywords, ignoring case and accents |
| `harness` | only when the run could not happen (workspace did not start, docker error); the detail says why |

Metrics are recorded, not graded: tokens come from OpenCode's own store in
the workspace (ACP does not report usage), so they are `null` if its layout
changes.

## Add a scenario

Add `scenarios/<id>.yaml`, then rebuild the image (or mount the folder with
`-v "$PWD/evals/scenarios:/evals/scenarios:ro"`) and pass `--scenario <id>`.

```yaml
id: my-scenario                 # = file name
title: Short description
prompts:                        # sent in order, each after the previous turn ends
  - "La question, en français…"
timeout_s: 900                  # per prompt
notebook:
  path: /workspace/notebook.py  # default
  must_change: true             # default
  must_run: true                # default
  run_timeout_s: 300            # default
  checks:                       # regexes on the final notebook
    - name: uniprot_accession
      why: optional, for readers
      pattern: 'P04637'
      flags: i                  # JavaScript RegExp flags, default "i"
answer:
  language: fr                  # checks the last turn's text is French
  keywords:                     # each passes if any of the strings appears
    - name: pathogenic
      any: ["pathogène"]
```

The scenario is validated (regexes compile, names unique) before any container
starts. [`scenarios/tp53-r175h.yaml`](scenarios/tp53-r175h.yaml) is the
Workbench demo.

## Develop

No Bun on the host? Use the image:

```sh
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/evals:/w" -w /w oven/bun:1.4-slim \
  sh -c 'bun install && bun test && bunx tsc --noEmit'
```

The tests cover the graders, the scenario validation and the summary; the
docker and WebSocket parts are exercised by a run against the mock model.
