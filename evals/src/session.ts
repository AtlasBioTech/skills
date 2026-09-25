// Drives one session over the bridge WebSocket (workbench docs/contracts.md
// §1): sends the scenario's prompts one turn at a time, answers permission
// requests like a user who always clicks "allow", and keeps every frame.

export type Frame = { type: string; id?: number; ts?: string; [key: string]: any };

export type Turn = {
  prompt: string;
  /** ACP stopReason, "error" from the bridge, or "timeout"/"disconnected" from us. */
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

export type SessionResult = {
  sessionId: string | null;
  frames: Frame[];
  turns: Turn[];
  permissions: PermissionRecord[];
  errors: string[];
};

type Options = {
  url: string;
  prompts: string[];
  timeoutMs: number;
  /** Called for every frame, for live progress. */
  onFrame?: (frame: Frame) => void;
};

/** How long to wait for turn_end after asking the agent to cancel. */
const CANCEL_GRACE_MS = 15_000;

export function runSession({ url, prompts, timeoutMs, onFrame }: Options): Promise<SessionResult> {
  const result: SessionResult = { sessionId: null, frames: [], turns: [], permissions: [], errors: [] };
  const ws = new WebSocket(url);
  let turnIndex = -1;
  let turnStarted = 0;
  let text = "";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelled = false;

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      ws.close();
      resolve(result);
    };

    const endTurn = (stopReason: string) => {
      result.turns.push({ prompt: prompts[turnIndex]!, stopReason, text, seconds: (performance.now() - turnStarted) / 1000 });
      clearTimeout(timer);
      if (stopReason === "timeout" || stopReason === "disconnected") return finish();
      nextPrompt();
    };

    const nextPrompt = () => {
      turnIndex++;
      if (turnIndex >= prompts.length) return finish();
      text = "";
      cancelled = false;
      turnStarted = performance.now();
      ws.send(JSON.stringify({ type: "prompt", text: prompts[turnIndex] }));
      timer = setTimeout(onTimeout, timeoutMs);
    };

    // A stuck turn is cancelled first, so the agent's partial work (and the
    // notebook it left) can still be graded; if even cancel hangs, give up.
    const onTimeout = () => {
      if (!cancelled) {
        cancelled = true;
        result.errors.push(`turn ${turnIndex + 1} timed out after ${timeoutMs / 1000} s; cancelled`);
        ws.send(JSON.stringify({ type: "cancel" }));
        timer = setTimeout(onTimeout, CANCEL_GRACE_MS);
        return;
      }
      endTurn("timeout");
    };

    ws.onmessage = (event) => {
      if (done) return;
      const frame = JSON.parse(String(event.data)) as Frame;
      onFrame?.(frame);
      if (frame.type === "hello") {
        result.sessionId = frame.session?.sessionId ?? null;
        // A fresh workspace has no turns, but a reconnect must not re-prompt.
        if (turnIndex === -1) nextPrompt();
        return;
      }
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
          ws.send(JSON.stringify({ type: "permission", requestId: frame.requestId, optionId: option }));
          return;
        }
        case "error":
          result.errors.push(String(frame.message));
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
