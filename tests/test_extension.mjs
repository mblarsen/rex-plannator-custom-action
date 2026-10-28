import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import extension from "../pi-extension.ts";

const first = "01a180a8-9639-75ed-a165-86bbaa0cd84c";
const second = "01a180a8-9639-75ed-a165-86bbaa0cd84d";
const clear = "\x1b]7501;state=clear:id=plannotator\x1b\\";
let handlers, output, ctx, originalWrite, originalTTY, originalBlock;

beforeEach(() => {
  handlers = {};
  output = [];
  ctx = { mode: "tui", sessionManager: {
    getSessionId: () => first,
    getSessionFile: () => "/session.jsonl",
  } };
  originalWrite = process.stdout.write;
  originalTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
  originalBlock = process.env.REX_BLOCK;
  process.env.REX_BLOCK = "block:test";
  Object.defineProperty(process.stdout, "isTTY", { value: true, configurable: true });
  process.stdout.write = (text) => { output.push(text); return true; };
  extension({ on: (event, handler) => { handlers[event] = handler; } });
});

afterEach(() => {
  process.stdout.write = originalWrite;
  if (originalTTY) Object.defineProperty(process.stdout, "isTTY", originalTTY);
  else delete process.stdout.isTTY;
  if (originalBlock === undefined) delete process.env.REX_BLOCK;
  else process.env.REX_BLOCK = originalBlock;
});

test("reports the exact UUID using valid protocol ID segments", () => {
  handlers.session_start({}, ctx);
  const id = "plannotator/" + first.replaceAll("-", "");
  assert.equal(output.join(""), clear + `\x1b]7501;state=idle:app=pi:id=${id}\x1b\\`);
  for (const segment of id.split("/")) assert.ok(segment.length <= 32);
});

test("does not write outside Rex", () => {
  delete process.env.REX_BLOCK;
  handlers.session_start({}, ctx);
  assert.deepEqual(output, []);
});

test("does not write to redirected stdout", () => {
  Object.defineProperty(process.stdout, "isTTY", { value: false, configurable: true });
  handlers.session_start({}, ctx);
  assert.deepEqual(output, []);
});

test("does not write in RPC or print mode", () => {
  for (const mode of ["rpc", "print", "json"]) handlers.session_start({}, { ...ctx, mode });
  assert.deepEqual(output, []);
});

test("does not report an ephemeral session", () => {
  ctx.sessionManager.getSessionFile = () => undefined;
  handlers.session_start({}, ctx);
  assert.deepEqual(output, []);
});

test("rejects malformed IDs and terminal-control injection", () => {
  for (const id of ["bad", first + ":state=working", "\x1b]7501;state=clear\x07"]) {
    ctx.sessionManager.getSessionId = () => id;
    handlers.session_start({}, ctx);
  }
  assert.deepEqual(output, []);
});

test("shutdown clears only its own record and is idempotent", () => {
  handlers.session_start({}, ctx);
  handlers.session_shutdown();
  handlers.session_shutdown();
  assert.equal(output.length, 2);
  assert.equal(output[1], clear);
  assert.ok(!output.includes("\x1b]7501;state=clear\x1b\\"));
});

test("a new runtime clears the previous session record before publishing", () => {
  handlers.session_start({}, ctx);
  handlers.session_shutdown();
  extension({ on: (event, handler) => { handlers[event] = handler; } });
  ctx.sessionManager.getSessionId = () => second;
  handlers.session_start({}, ctx);
  assert.equal(output.length, 3);
  assert.ok(output[2].startsWith(clear));
  assert.ok(output[2].includes(second.replaceAll("-", "")));
  assert.ok(!output[2].includes(first.replaceAll("-", "")));
});

test("agent lifecycle republishes after a terminal status reset", () => {
  handlers.session_start({}, ctx);
  handlers.agent_start({}, ctx);
  handlers.agent_settled({}, ctx);
  assert.equal(output.length, 3);
  assert.equal(output[0], output[1]);
  assert.equal(output[1], output[2]);
});

test("losing a file-backed session removes the old identity", () => {
  handlers.session_start({}, ctx);
  ctx.sessionManager.getSessionFile = () => undefined;
  handlers.agent_start({}, ctx);
  handlers.session_shutdown();
  assert.deepEqual(output.slice(1), [clear]);
});
