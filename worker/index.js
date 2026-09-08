/**
 * ONYX license verification worker.
 *
 * GET /verify?key=<LICENSE_KEY>&machine_id=<MACHINE_ID>
 *
 * KV record shape stored under the license key:
 *   { "active": true, "bound_machine_id": "<hash>|null" }
 *
 * Responses:
 *   400 { valid: false, error: ... }  - missing key or machine_id
 *   403 { valid: false, error: ... }  - key is bound to a different machine
 *   200 { valid: true }               - unbound (auto-binds now) or matching device
 *   200 { valid: false, error: ... }  - unknown key or inactive key
 */

function jsonResponse(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function handleVerify(request, env) {
  const url = new URL(request.url);
  const key = url.searchParams.get("key");
  const machineId = url.searchParams.get("machine_id");

  if (!key || !machineId) {
    return jsonResponse(
      { valid: false, error: "Missing required parameter: key and machine_id are required" },
      400
    );
  }

  const raw = await env.LICENSES.get(key);
  if (!raw) {
    return jsonResponse({ valid: false, error: "Unknown license key" }, 200);
  }

  let record;
  try {
    record = JSON.parse(raw);
  } catch {
    return jsonResponse({ valid: false, error: "Corrupt license record" }, 200);
  }

  if (record.active === false) {
    return jsonResponse({ valid: false, error: "License inactive" }, 200);
  }

  const boundMachineId = record.bound_machine_id || null;

  if (!boundMachineId) {
    record.bound_machine_id = machineId;
    await env.LICENSES.put(key, JSON.stringify(record));
    return jsonResponse({ valid: true }, 200);
  }

  if (boundMachineId === machineId) {
    return jsonResponse({ valid: true }, 200);
  }

  return jsonResponse(
    { valid: false, error: "License already bound to another machine" },
    403
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/verify" && request.method === "GET") {
      return handleVerify(request, env);
    }

    return jsonResponse({ valid: false, error: "Not found" }, 404);
  },
};

export { handleVerify };
