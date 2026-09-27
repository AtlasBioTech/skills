// The session driver against a fake bridge that speaks docs/contracts.md §1:
// the order of create / open / prompt and what each carries.

import { afterEach, expect, test } from "bun:test";
import type { Server } from "bun";
import { runSession, type Frame, type Opened } from "../src/session";

type Fake = { server: Server<undefined>; received: Frame[] };
let fake: Fake | undefined;
afterEach(() => fake?.server.stop(true));

/** A bridge with one project, "demo", whose create/open/prompt answer like the real one. */
function fakeBridge(opts: { refusePrompt?: boolean } = {}): Fake {
  const received: Frame[] = [];
  const server = Bun.serve({
    port: 0,
    fetch: (req, srv) => (srv.upgrade(req) ? undefined : new Response("no", { status: 400 })),
    websocket: {
      open: (ws) => {
        ws.send(JSON.stringify({ type: "workspace", agent: {}, model: {}, projects: [] }));
      },
      message: (ws, raw) => {
        const msg = JSON.parse(String(raw)) as Frame;
        received.push(msg);
        const send = (f: object) => void ws.send(JSON.stringify(f));
        if (msg.type === "create" && msg.kind === "project") {
          send({ type: "created", kind: "project", project: msg.name, path: "notebooks/analyse.py", conversation: "c1" });
          send({ type: "workspace", agent: {}, model: {}, projects: [] });
        } else if (msg.type === "create" && msg.kind === "notebook") {
          send({ type: "created", kind: "notebook", project: msg.project, path: `notebooks/${msg.name.toLowerCase()}.py` });
        } else if (msg.type === "open") {
          send({ type: "hello", session: { project: msg.project, conversation: msg.conversation, sessionId: "" }, history: [] });
        } else if (msg.type === "prompt") {
          if (opts.refusePrompt) return send({ type: "refused", message: "Ce notebook n'est pas dans le projet." });
          send({ type: "user", id: 1, ts: "", text: msg.text, notebook: msg.notebook });
          send({ type: "turn_start", id: 2, ts: "" });
          send({ type: "workspace", agent: {}, model: {}, projects: [] });
          send({ type: "update", id: 3, ts: "", update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "Bonjour" } } });
          send({ type: "turn_end", id: 4, ts: "", stopReason: "end_turn" });
        }
      },
    },
  });
  return { server, received };
}

test("creates a project, opens its first conversation, prompts with the active notebook", async () => {
  fake = fakeBridge();
  const opened: Opened[] = [];
  const res = await runSession({
    url: `ws://127.0.0.1:${fake.server.port}/ws`,
    project: "tp53",
    prompts: ["q1", "q2"],
    timeoutMs: 5000,
    onOpen: async (o) => void opened.push({ ...o }),
  });
  expect(fake.received.map((f) => f.type)).toEqual(["create", "open", "prompt", "prompt"]);
  expect(fake.received[1]).toEqual({ type: "open", project: "tp53", conversation: "c1" });
  expect(fake.received[2]).toEqual({ type: "prompt", text: "q1", notebook: "notebooks/analyse.py" });
  expect(opened).toEqual([{ project: "tp53", conversation: "c1", notebook: "notebooks/analyse.py" }]);
  expect(res.turns.map((t) => [t.stopReason, t.text])).toEqual([["end_turn", "Bonjour"], ["end_turn", "Bonjour"]]);
  // Only the conversation's frames are kept.
  expect(res.frames.some((f) => f.type === "workspace")).toBe(false);
  expect(res.errors).toEqual([]);
});

test("a scenario's notebook name is created and becomes the active notebook", async () => {
  fake = fakeBridge();
  const res = await runSession({ url: `ws://127.0.0.1:${fake.server.port}/ws`, project: "p", notebook: "BRCA1", prompts: ["q"], timeoutMs: 5000 });
  expect(fake.received[1]).toEqual({ type: "create", kind: "notebook", project: "p", name: "BRCA1" });
  expect(fake.received.at(-1)).toEqual({ type: "prompt", text: "q", notebook: "notebooks/brca1.py" });
  expect(res.opened.notebook).toBe("notebooks/brca1.py");
});

test("a refused prompt ends the run with an error instead of waiting for the timeout", async () => {
  fake = fakeBridge({ refusePrompt: true });
  const res = await runSession({ url: `ws://127.0.0.1:${fake.server.port}/ws`, project: "p", prompts: ["q1", "q2"], timeoutMs: 60_000 });
  expect(res.turns.map((t) => t.stopReason)).toEqual(["refused"]);
  expect(res.errors[0]).toContain("refused");
});

test("a bridge that never answers the connect fails the setup", async () => {
  const server = Bun.serve({ port: 0, fetch: (req, srv) => (srv.upgrade(req) ? undefined : new Response()), websocket: { message: () => {} } });
  fake = { server, received: [] };
  await expect(runSession({ url: `ws://127.0.0.1:${server.port}/ws`, project: "p", prompts: ["q"], timeoutMs: 5000, setupTimeoutMs: 300 })).rejects.toThrow(
    /waiting for workspace/,
  );
});
