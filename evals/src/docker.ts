// Workspace containers, through the docker CLI (the runner image ships it and
// talks to the host daemon over the mounted socket). One fresh container per
// run, so no run sees another's notebook, session or OpenCode state.

export type Exec = { exitCode: number; stdout: string; stderr: string; timedOut: boolean };

/** Runs `docker <args>`; `env` is added to the CLI's environment (for `-e NAME` without a value). */
export async function docker(args: string[], opts: { env?: Record<string, string>; timeoutMs?: number } = {}): Promise<Exec> {
  const proc = Bun.spawn(["docker", ...args], {
    env: { ...process.env, ...opts.env },
    stdout: "pipe",
    stderr: "pipe",
  });
  let timedOut = false;
  const timer = opts.timeoutMs
    ? setTimeout(() => {
        timedOut = true;
        proc.kill();
      }, opts.timeoutMs)
    : undefined;
  const [stdout, stderr, exitCode] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text(), proc.exited]);
  clearTimeout(timer);
  return { exitCode, stdout, stderr, timedOut };
}

export type WorkspaceSpec = {
  name: string;
  image: string;
  network: string;
  label: string;
  cpus: string;
  memory: string;
  baseUrl: string;
  model: string;
  provider: string;
  /** Passed through the CLI's environment, never on its command line. */
  apiKey: string;
};

export async function startWorkspace(spec: WorkspaceSpec): Promise<void> {
  const args = [
    "run", "-d",
    "--name", spec.name,
    "--network", spec.network,
    "--label", `atlas.evals.run=${spec.label}`,
    "--cpus", spec.cpus,
    "--memory", spec.memory,
    "-e", `ATLAS_LLM_BASE_URL=${spec.baseUrl}`,
    "-e", `ATLAS_LLM_MODEL=${spec.model}`,
    "-e", `ATLAS_MODEL_PROVIDER=${spec.provider}`,
    // No "=value": docker reads it from our environment, so the key does not
    // appear in `ps` output or in an error message quoting the command.
    "-e", "ATLAS_LLM_API_KEY",
    spec.image,
  ];
  const res = await docker(args, { env: { ATLAS_LLM_API_KEY: spec.apiKey } });
  if (res.exitCode !== 0) throw new Error(`docker run ${spec.image} failed: ${res.stderr.trim()}`);
}

/** Polls the bridge's /healthz (200 once OpenCode has an ACP session). */
export async function waitHealthy(name: string, port: number, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let last = "no answer";
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://${name}:${port}/healthz`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) return;
      last = `HTTP ${res.status} ${(await res.text()).slice(0, 200)}`;
    } catch (err) {
      last = (err as Error).message;
    }
    const state = await docker(["inspect", "-f", "{{.State.Running}}", name]);
    if (state.stdout.trim() !== "true") throw new Error(`workspace exited before becoming healthy (last healthz: ${last})`);
    await Bun.sleep(1000);
  }
  throw new Error(`workspace not healthy after ${timeoutMs / 1000} s (last healthz: ${last})`);
}

export async function execIn(name: string, cmd: string[], timeoutMs?: number): Promise<Exec> {
  return docker(["exec", "-w", "/workspace", name, ...cmd], { timeoutMs });
}

/** File content, or null if it does not exist. */
export async function readFileIn(name: string, path: string): Promise<string | null> {
  const res = await execIn(name, ["cat", path]);
  return res.exitCode === 0 ? res.stdout : null;
}

export async function logsOf(name: string): Promise<string> {
  const res = await docker(["logs", "--tail", "300", name]);
  return res.stdout + res.stderr;
}

export async function removeContainer(name: string): Promise<void> {
  await docker(["rm", "-f", name]);
}

/** Removes every container of this invocation (on Ctrl-C). */
export async function removeLabelled(label: string): Promise<void> {
  const ids = await docker(["ps", "-aq", "--filter", `label=atlas.evals.run=${label}`]);
  const list = ids.stdout.split("\n").filter(Boolean);
  if (list.length) await docker(["rm", "-f", ...list]);
}
