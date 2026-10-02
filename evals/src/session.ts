// Drives one conversation over the bridge WebSocket (workbench
// docs/contracts.md §1): creates a project for the scenario, opens its first
// conversation, sends the scenario's prompts one turn at a time with the
// active notebook, answers permission requests like a user who always clicks
// "allow", and keeps every frame of the conversation.

export type Frame = { type: string; id?: number; ts?: string; [key: string]: any };

export type Turn = {
  prompt: string;
  /** ACP stopReason, "error" from the bridge, or "timeout"/"disconnected"/"refused" from us. */
  stopReason: string;
  /** Everything the agent said in this turn (agent_message_chunk text). */
  text: string;
  seconds: number;
};

export type PermissionRecord = {
  requestId: string;
  title: string;
  kind: string;
  optionId: string;
};

/** Where the conversation happens: what `create` made and `open` opened. */
export type Opened = {
  /** The project's folder name, relative to the workspace root. */
  project: string;
  conversation: string;
  /** The active notebook, relative to the project ("notebooks/analyse.py"). */
  notebook: string;
};

export type SessionResult = {
  opened: Opened;
  /** The ACP session id from `hello`: "" until the conversation's first prompt. */
  sessionId: string;
  /** The conversation's frames (not the workspace-level `workspace`/`created` frames). */
  frames: Frame[];
  turns: Turn[];
  permissions: PermissionRecord[];
  errors: string[];
};

type Options = {
  url: string;
  /** Name of the project to create; the bridge may suffix it if taken. */
  project: string;
  /** Create this notebook in the project and make it the active one; else the project's first notebook. */
  notebook?: string;
  prompts: string[];
  timeoutMs: number;
  /** How long creating and opening the project may take. */
  setupTimeoutMs?: number;
  /** Awaited once the conversation is open, before the first prompt (to snapshot the notebooks). */
  onOpen?: (opened: Opened) => Promise<void>;
  /** Called for every frame, for live progress. */
  onFrame?: (frame: Frame) => void;
};

/** How long to wait for turn_end after asking the agent to cancel. */
const CANCEL_GRACE_MS = 15_000;

/**
 * Resolves with the conversation once every prompt's turn has ended (or timed
 * out); rejects when the project could not be created and opened, which is a
 * harness failure rather than the model's.
 */
export function runSession({ url, project, notebook, prompts, timeoutMs, setupTimeoutMs = 60_000, onOpen, onFrame }: Options): Promise<SessionResult> {
  const result: SessionResult = {
    opened: { project: "", conversation: "", notebook: "" },
    sessionId: "",
    frames: [],
    turns: [],
    permissions: [],
    errors: [],
  };
  const ws = new WebSocket(url);
  // setup: waiting for the workspace, the project, the notebook, the hello.
  let phase: "workspace" | "project" | "notebook" | "hello" | "turns" = "workspace";
  let turnIndex = -1;
  let turnStarted = 0;
  let text = "";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelled = false;

  return new Promise((resolve, reject) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      ws.close();
      resolve(result);
    };
    const failSetup = (why: string) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      ws.close();
      reject(new Error(`could not open a conversation: ${why}`));
    };
    const send = (frame: object) => ws.send(JSON.stringify(frame));
    timer = setTimeout(() => failSetup(`no hello after ${setupTimeoutMs / 1000} s (waiting for ${phase})`), setupTimeoutMs);

    const endTurn = (stopReason: string) => {
      result.turns.push({ prompt: prompts[turnIndex]!, stopReason, text, seconds: (performance.now() - turnStarted) / 1000 });
      clearTimeout(timer);
      if (stopReason === "timeout" || stopReason === "disconnected" || stopReason === "refused") return finish();
      nextPrompt();
    };

    const nextPrompt = () => {
      turnIndex++;
      if (turnIndex >= prompts.length) return finish();
      text = "";
      cancelled = false;
      turnStarted = performance.now();
      send({ type: "prompt", text: prompts[turnIndex], notebook: result.opened.notebook });
      timer = setTimeout(onTimeout, timeoutMs);
    };

    // A stuck turn is cancelled first, so the agent's partial work (and the
    // notebook it left) can still be graded; if even cancel hangs, give up.
    const onTimeout = () => {
      if (!cancelled) {
        cancelled = true;
        result.errors.push(`turn ${turnIndex + 1} timed out after ${timeoutMs / 1000} s; cancelled`);
        send({ type: "cancel" });
        timer = setTimeout(onTimeout, CANCEL_GRACE_MS);
        return;
      }
      endTurn("timeout");
    };

    const open = () => {
      phase = "hello";
      send({ type: "open", project: result.opened.project, conversation: result.opened.conversation });
    };

    // Creating and opening the project, in the order the UI does it.
    const setup = (frame: Frame) => {
      if (frame.type === "refused") return failSetup(`refused while waiting for ${phase}: ${frame.message}`);
      if (phase === "workspace" && frame.type === "workspace") {
        phase = "project";
        return send({ type: "create", kind: "project", name: project });
      }
      if (phase === "project" && frame.type === "created" && frame.kind === "project") {
        result.opened = { project: frame.project, conversation: frame.conversation ?? "", notebook: frame.path ?? "" };
        if (!result.opened.conversation) return failSetup("the created project has no conversation");
        if (!notebook) {
          if (!result.opened.notebook) return failSetup("the created project has no notebook");
          return open();
        }
        phase = "notebook";
        return send({ type: "create", kind: "notebook", project: result.opened.project, name: notebook });
      }
      if (phase === "notebook" && frame.type === "created" && frame.kind === "notebook") {
        result.opened.notebook = frame.path ?? "";
        return open();
      }
      if (phase === "hello" && frame.type === "hello") {
        clearTimeout(timer);
        phase = "turns";
        result.sessionId = frame.session?.sessionId ?? "";
        const start = () => {
          if (!done) nextPrompt();
        };
        return void (onOpen ? onOpen(result.opened).then(start, (err) => failSetup((err as Error).message)) : start());
      }
      // Anything else (a `workspace` refresh after the project appeared) is not ours to act on.
    };

    ws.onmessage = (event) => {
      if (done) return;
      const frame = JSON.parse(String(event.data)) as Frame;
      onFrame?.(frame);
      if (phase !== "turns") return setup(frame);
      // Workspace-level frames: every file the agent writes triggers a fresh
      // `workspace`; they are not part of the conversation.
      if (frame.type === "workspace" || frame.type === "created" || frame.type === "renamed") return;
      result.frames.push(frame);
      switch (frame.type) {
        case "update": {
          const u = frame.update;
          if (u?.sessionUpdate === "agent_message_chunk" && u.content?.type === "text") text += u.content.text;
          return;
        }
        case "permission_request": {
          const option = pickAllow(frame.options ?? []);
          result.permissions.push({
            requestId: frame.requestId,
            title: frame.toolCall?.title ?? "",
            kind: frame.toolCall?.kind ?? "",
            optionId: option,
          });
          send({ type: "permission", requestId: frame.requestId, optionId: option });
          return;
        }
        case "error":
          result.errors.push(String(frame.message));
          return;
        case "refused":
          // A prompt the bridge would not take (e.g. a notebook not in the project): no turn will follow.
          result.errors.push(`refused: ${frame.message}`);
          if (turnIndex >= 0 && turnIndex < prompts.length) endTurn("refused");
          return;
        case "turn_end":
          if (turnIndex >= 0 && turnIndex < prompts.length) endTurn(cancelled ? "timeout" : String(frame.stopReason));
          return;
      }
    };
    ws.onerror = () => {
      result.errors.push(`WebSocket error on ${url}`);
    };
    ws.onclose = () => {
      if (done) return;
      if (phase !== "turns") return failSetup(`the bridge closed the WebSocket while waiting for ${phase}`);
      if (turnIndex >= 0 && turnIndex < prompts.length) {
        result.errors.push("bridge closed the WebSocket during a turn");
        endTurn("disconnected");
      }
      finish();
    };
  });
}

/** Prefer a one-time allow, so each request is recorded as asked. */
export function pickAllow(options: { optionId: string; kind?: string }[]): string {
  const byKind = (kind: string) => options.find((o) => o.kind === kind)?.optionId;
  return byKind("allow_once") ?? byKind("allow_always") ?? options[0]?.optionId ?? "cancelled";
}

export type ToolStats = { calls: number; failed: number; byKind: Record<string, number> };

/** Counts tool calls from ACP tool_call / tool_call_update frames, by id. */
export function toolStats(frames: Frame[]): ToolStats {
  const calls = new Map<string, { kind: string; status: string }>();
  for (const f of frames) {
    const u = f.type === "update" ? f.update : undefined;
    if (!u || (u.sessionUpdate !== "tool_call" && u.sessionUpdate !== "tool_call_update")) continue;
    const prev = calls.get(u.toolCallId) ?? { kind: "other", status: "pending" };
    calls.set(u.toolCallId, { kind: u.kind ?? prev.kind, status: u.status ?? prev.status });
  }
  const byKind: Record<string, number> = {};
  let failed = 0;
  for (const c of calls.values()) {
    byKind[c.kind] = (byKind[c.kind] ?? 0) + 1;
    if (c.status === "failed") failed++;
  }
  return { calls: calls.size, failed, byKind };
}

/**
 * One string per tool call, for the scenario's `tools` checks: every title
 * and input its tool_call / tool_call_update frames carried, one per line
 * (OpenCode sends the command or the file content in rawInput).
 */
export function toolCallTexts(frames: Frame[]): string[] {
  const calls = new Map<string, string[]>();
  for (const f of frames) {
    const u = f.type === "update" ? f.update : undefined;
    if (!u || (u.sessionUpdate !== "tool_call" && u.sessionUpdate !== "tool_call_update")) continue;
    const parts = calls.get(u.toolCallId) ?? [];
    if (typeof u.title === "string") parts.push(u.title);
    if (u.rawInput !== undefined) parts.push(JSON.stringify(u.rawInput));
    calls.set(u.toolCallId, parts);
  }
  return [...calls.values()].map((parts) => parts.join("\n"));
}

/**
 * The skills the agent loaded (OpenCode's `skill` tool: the name is in the
 * update's rawInput, and the completed call is titled "Loaded skill: <name>").
 */
export function skillsLoaded(frames: Frame[]): string[] {
  const names = new Set<string>();
  for (const f of frames) {
    const u = f.type === "update" ? f.update : undefined;
    if (!u || (u.sessionUpdate !== "tool_call" && u.sessionUpdate !== "tool_call_update")) continue;
    if (u.title === "skill" && typeof u.rawInput?.name === "string") names.add(u.rawInput.name);
    const loaded = typeof u.title === "string" ? u.title.match(/^Loaded skill: (.+)$/) : null;
    if (loaded) names.add(loaded[1]!.trim());
  }
  return [...names].sort();
}
