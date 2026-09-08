// Plain-Node test for the license worker (no test framework dependency).
// Run with: node worker/index.test.js
import assert from "node:assert/strict";
import { handleVerify } from "./index.js";

function makeKv(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, value);
    },
    _store: store,
  };
}

function req(query) {
  return new Request(`https://example.workers.dev/verify?${query}`);
}

async function run(name, fn) {
  try {
    await fn();
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

await run("missing key and machine_id -> 400", async () => {
  const kv = makeKv();
  const res = await handleVerify(req(""), { LICENSES: kv });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.valid, false);
});

await run("missing machine_id only -> 400", async () => {
  const kv = makeKv();
  const res = await handleVerify(req("key=ABC123"), { LICENSES: kv });
  assert.equal(res.status, 400);
});

await run("unknown key -> 200 valid:false", async () => {
  const kv = makeKv();
  const res = await handleVerify(req("key=NOPE&machine_id=m1"), { LICENSES: kv });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.valid, false);
});

await run("first use auto-binds and returns valid", async () => {
  const kv = makeKv({ ABC: JSON.stringify({ active: true, bound_machine_id: null }) });
  const res = await handleVerify(req("key=ABC&machine_id=m1"), { LICENSES: kv });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.valid, true);
  const stored = JSON.parse(await kv.get("ABC"));
  assert.equal(stored.bound_machine_id, "m1");
});

await run("matching device returns valid", async () => {
  const kv = makeKv({ ABC: JSON.stringify({ active: true, bound_machine_id: "m1" }) });
  const res = await handleVerify(req("key=ABC&machine_id=m1"), { LICENSES: kv });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.valid, true);
});

await run("device mismatch returns 403", async () => {
  const kv = makeKv({ ABC: JSON.stringify({ active: true, bound_machine_id: "m1" }) });
  const res = await handleVerify(req("key=ABC&machine_id=m2"), { LICENSES: kv });
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.valid, false);
});

await run("inactive key returns valid:false", async () => {
  const kv = makeKv({ ABC: JSON.stringify({ active: false, bound_machine_id: "m1" }) });
  const res = await handleVerify(req("key=ABC&machine_id=m1"), { LICENSES: kv });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.valid, false);
});

if (process.exitCode) {
  console.error("Some worker tests failed.");
} else {
  console.log("All worker tests passed.");
}
