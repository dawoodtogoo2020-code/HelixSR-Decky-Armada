// Run: node --experimental-strip-types --test tests/test_armada_read_rpc.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  createArmadaReadRpc,
  ARMADA_READ_METHODS,
  ARMADA_READ_TIMEOUT_MESSAGE,
  DEFAULT_ARMADA_READ_TIMEOUT_MS,
  MAX_ARMADA_READ_TIMEOUT_MS,
} from "../src/armadaReadRpc.ts";

const TIMEOUT_MESSAGE =
  "HelixSR did not respond. Refresh games and status; if it repeats, reopen the plugin after Decky restarts.";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// Manual fake timers: deterministic, no wall-clock waiting.
function installFakeTimers(t) {
  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;
  const timers = new Map();
  let nextId = 1;
  let cleared = 0;
  globalThis.setTimeout = (fn, ms) => {
    const id = nextId++;
    timers.set(id, { fn, ms });
    return id;
  };
  globalThis.clearTimeout = (id) => {
    if (timers.delete(id)) cleared += 1;
  };
  t.after(() => {
    globalThis.setTimeout = realSetTimeout;
    globalThis.clearTimeout = realClearTimeout;
  });
  return {
    timers,
    get cleared() {
      return cleared;
    },
    fireAll() {
      for (const [id, { fn }] of [...timers]) {
        timers.delete(id);
        fn();
      }
    },
  };
}

// setImmediate is not faked, so this drains pending microtasks.
const flush = () => new Promise((resolve) => setImmediate(resolve));

function mockRpc(impl) {
  const calls = [];
  const rpc = (method, ...args) => {
    calls.push({ method, args });
    return impl(method, ...args);
  };
  return { rpc, calls };
}

test("exports the expected constants", () => {
  assert.equal(ARMADA_READ_TIMEOUT_MESSAGE, TIMEOUT_MESSAGE);
  assert.equal(DEFAULT_ARMADA_READ_TIMEOUT_MS, 30000);
  assert.equal(MAX_ARMADA_READ_TIMEOUT_MS, 120000);
  assert.deepEqual(
    [...ARMADA_READ_METHODS],
    ["library", "armada_source_status", "armada_status", "armada_model_status", "helix2_library", "helix2_status"],
  );
});

test("validates timeout as a finite positive integer up to 120000", () => {
  const { rpc } = mockRpc(() => Promise.resolve(null));
  for (const bad of [0, -1, 1.5, NaN, Infinity, -Infinity, 120001, "30000", null]) {
    assert.throws(() => createArmadaReadRpc(rpc, bad), RangeError, `timeout ${String(bad)}`);
  }
  assert.doesNotThrow(() => createArmadaReadRpc(rpc, 1));
  assert.doesNotThrow(() => createArmadaReadRpc(rpc, 120000));
  assert.doesNotThrow(() => createArmadaReadRpc(rpc));
  assert.throws(() => createArmadaReadRpc(undefined, 1000), TypeError);
});

test("defaults to a 30000 ms budget", async (t) => {
  const clock = installFakeTimers(t);
  const value = { synthetic: true };
  const { rpc } = mockRpc(() => Promise.resolve(value));
  const read = createArmadaReadRpc(rpc);
  const result = read("armada_status");
  assert.equal(clock.timers.size, 1);
  assert.equal([...clock.timers.values()][0].ms, 30000);
  assert.equal(await result, value);
});

test("allowed read methods dispatch once with args and preserve the value", async (t) => {
  const clock = installFakeTimers(t);
  for (const method of ["library", "armada_source_status", "armada_status", "armada_model_status"]) {
    const value = { method, items: [1, 2] };
    const { rpc, calls } = mockRpc(() => Promise.resolve(value));
    const read = createArmadaReadRpc(rpc, 50);
    const result = await read(method, "arg-a", 7);
    assert.equal(result, value, `${method} returns the same object`);
    assert.deepEqual(calls, [{ method, args: ["arg-a", 7] }]);
  }
  assert.equal(clock.timers.size, 0, "all timers cleared after early success");
});

test("unknown and mutating methods reject before dispatch", async (t) => {
  const clock = installFakeTimers(t);
  const { rpc, calls } = mockRpc(() => Promise.resolve("should not happen"));
  const read = createArmadaReadRpc(rpc, 50);
  for (const method of [
    "armada_activate",
    "set_setting",
    "armada_select_source",
    "start_game",
    "",
    "LIBRARY",
    "toString",
    "__proto__",
    "constructor",
    undefined,
    42,
  ]) {
    await assert.rejects(read(method), /only allows read methods/);
  }
  assert.equal(calls.length, 0);
  assert.equal(clock.timers.size, 0, "no timer scheduled for rejected methods");
});

test("never-settling read rejects with the human message after the budget", async (t) => {
  const clock = installFakeTimers(t);
  const { rpc, calls } = mockRpc(() => new Promise(() => {}));
  const read = createArmadaReadRpc(rpc, 25);
  let outcome = "pending";
  const result = read("library").then(
    () => (outcome = "resolved"),
    (error) => {
      outcome = error;
    },
  );
  await flush();
  assert.equal(outcome, "pending", "does not settle before the timer fires");
  assert.equal([...clock.timers.values()][0].ms, 25);
  clock.fireAll();
  await result;
  assert.ok(outcome instanceof Error);
  assert.equal(outcome.message, TIMEOUT_MESSAGE);
  assert.equal(calls.length, 1, "called exactly once, no retry");
  await flush();
  assert.equal(calls.length, 1, "still no retry after timeout");
});

test("early rejection preserves the original error and clears the timer", async (t) => {
  const clock = installFakeTimers(t);
  const original = new Error("synthetic backend failure");
  original.code = "SYNTHETIC";
  const { rpc, calls } = mockRpc(() => Promise.reject(original));
  const read = createArmadaReadRpc(rpc, 50);
  await assert.rejects(read("armada_model_status"), (error) => error === original);
  assert.equal(calls.length, 1);
  assert.equal(clock.timers.size, 0);
  assert.equal(clock.cleared, 1);
});

test("synchronous throw preserves the original error and clears the timer", async (t) => {
  const clock = installFakeTimers(t);
  const original = new TypeError("synthetic sync throw");
  const { rpc, calls } = mockRpc(() => {
    throw original;
  });
  const read = createArmadaReadRpc(rpc, 50);
  await assert.rejects(read("armada_source_status"), (error) => error === original);
  assert.equal(calls.length, 1);
  assert.equal(clock.timers.size, 0);
});

test("late rejection after timeout does not cause unhandledRejection", async (t) => {
  const clock = installFakeTimers(t);
  const unhandled = [];
  const onUnhandled = (reason) => unhandled.push(reason);
  process.on("unhandledRejection", onUnhandled);
  t.after(() => process.off("unhandledRejection", onUnhandled));

  const backend = deferred();
  const { rpc, calls } = mockRpc(() => backend.promise);
  const read = createArmadaReadRpc(rpc, 25);
  const result = read("armada_status");
  clock.fireAll();
  await assert.rejects(result, { message: TIMEOUT_MESSAGE });

  backend.reject(new Error("synthetic late failure"));
  await flush();
  await flush();
  assert.deepEqual(unhandled, []);
  assert.equal(calls.length, 1);
});

test("late resolution after timeout is ignored", async (t) => {
  const clock = installFakeTimers(t);
  const backend = deferred();
  const { rpc } = mockRpc(() => backend.promise);
  const read = createArmadaReadRpc(rpc, 25);
  const outcomes = [];
  const result = read("library").then(
    (value) => outcomes.push(["resolved", value]),
    (error) => outcomes.push(["rejected", error.message]),
  );
  clock.fireAll();
  await result;
  backend.resolve({ late: true });
  await flush();
  assert.deepEqual(outcomes, [["rejected", TIMEOUT_MESSAGE]]);
});

test("settles only once when success arrives before the deadline", async (t) => {
  const clock = installFakeTimers(t);
  const backend = deferred();
  const { rpc } = mockRpc(() => backend.promise);
  const read = createArmadaReadRpc(rpc, 25);
  const outcomes = [];
  const result = read("armada_model_status").then(
    (value) => outcomes.push(["resolved", value]),
    (error) => outcomes.push(["rejected", error]),
  );
  const value = { ready: false };
  backend.resolve(value);
  await result;
  assert.equal(clock.timers.size, 0, "timer cleared after early success");
  clock.fireAll();
  await flush();
  assert.equal(outcomes.length, 1);
  assert.equal(outcomes[0][0], "resolved");
  assert.equal(outcomes[0][1], value);
});

test("each invocation dispatches independently exactly once", async (t) => {
  const clock = installFakeTimers(t);
  const first = deferred();
  const second = deferred();
  const queue = [first, second];
  const { rpc, calls } = mockRpc(() => queue.shift().promise);
  const read = createArmadaReadRpc(rpc, 25);
  const a = read("library");
  const b = read("armada_status");
  assert.equal(calls.length, 2);
  assert.equal(clock.timers.size, 2);
  second.resolve("b-value");
  assert.equal(await b, "b-value");
  assert.equal(clock.timers.size, 1);
  clock.fireAll();
  await assert.rejects(a, { message: TIMEOUT_MESSAGE });
  first.resolve("too late");
  await flush();
  assert.equal(calls.length, 2);
});

test("source stays browser-safe with no Node imports or extra I/O", () => {
  const source = readFileSync(new URL("../src/armadaReadRpc.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /from\s+["']node:/);
  assert.doesNotMatch(source, /\brequire\s*\(/);
  assert.doesNotMatch(source, /\bprocess\./);
  assert.doesNotMatch(source, /\bfetch\s*\(|WebSocket|child_process/);
});
