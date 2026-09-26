import assert from "node:assert/strict"
import test from "node:test"

import { bindSession, reviewEnvironment } from "../assets/platforms/opencode-v2/binding.mjs"

function clientFor(id, providerID, modelID) {
  const calls = []
  return {
    calls,
    session: {
      get: async ({ sessionID }) => {
        calls.push(["session", sessionID])
        return { data: { id: sessionID, model: { providerID, id: modelID, variant: "high" } } }
      },
    },
    model: {
      list: async () => {
        calls.push(["models"])
        return { data: [
          { providerID, id: "other-model", name: "Other" },
          { providerID, id: modelID, modelID: "upstream", name: id,
            capabilities: { tools: true, input: ["text"], output: ["text"] },
            limit: { context: 200000, output: 64000 },
            variants: [{ id: "high", settings: { reasoningEffort: "high" } }],
            headers: { Authorization: "not-copied" },
          },
        ] }
      },
    },
  }
}

test("binds only the exact V2 session provider, model, and variant", async () => {
  const client = clientFor("session-a", "provider-a", "model-a")
  const binding = await bindSession(client, "session-a")

  assert.deepEqual(client.calls, [
    ["session", "session-a"],
    ["models"],
  ])
  assert.equal(binding.model, "provider-a/model-a")
  assert.equal(binding.variant, "high")
  assert.equal(binding.providerID, "provider-a")
  assert.equal(binding.modelID, "model-a")
  assert.equal(binding.metadata, undefined)
})

test("parallel sessions remain bound to their explicit identity", async () => {
  const [a, b] = await Promise.all([
    bindSession(clientFor("session-a", "provider-a", "model-a"), "session-a"),
    bindSession(clientFor("session-b", "provider-b", "model-b"), "session-b"),
  ])

  assert.equal(a.model, "provider-a/model-a")
  assert.equal(b.model, "provider-b/model-b")
  assert.equal(a.sessionID, "session-a")
  assert.equal(b.sessionID, "session-b")
})

test("provider-owned routing does not gate the selected model", async () => {
  const binding = await bindSession(clientFor("session-a", "other-provider", "model-a"), "session-a")
  assert.equal(binding.model, "other-provider/model-a")
})

test("missing, duplicate, and unsafe session metadata fail closed", async () => {
  const missing = clientFor("session-a", "provider-a", "model-a")
  missing.model.list = async () => ({ data: [] })
  await assert.rejects(bindSession(missing, "session-a"), /missing or ambiguous/)

  const duplicate = clientFor("session-a", "provider-a", "model-a")
  duplicate.model.list = async () => ({ data: [
    { providerID: "provider-a", id: "model-a" },
    { providerID: "provider-a", id: "model-a" },
  ] })
  await assert.rejects(bindSession(duplicate, "session-a"), /missing or ambiguous/)

  const mismatched = clientFor("session-b", "provider-a", "model-a")
  mismatched.session.get = async () => ({ data: {
    id: "another-session", model: { providerID: "provider-a", id: "model-a" },
  } })
  await assert.rejects(bindSession(mismatched, "session-a"), /current session model/)

  const missingVariant = clientFor("session-a", "provider-a", "model-a")
  missingVariant.model.list = async () => ({ data: [{ providerID: "provider-a", id: "model-a", variants: [] }] })
  await assert.rejects(bindSession(missingVariant, "session-a"), /variant is unavailable/)
})

test("packet preparation receives only the model reference and nonsecret runtime context", () => {
  const env = reviewEnvironment({
    model: "provider-a/model-a",
  }, {
    PATH: "/safe/bin", HOME: "/home/user", XDG_DATA_HOME: "/home/user/.local/share",
    OPENAI_API_KEY: "do-not-copy", LEAN_REVIEW_CURRENT_MODEL: "stale",
  })

  assert.deepEqual(env, {
    PATH: "/safe/bin",
    HOME: "/home/user",
    XDG_DATA_HOME: "/home/user/.local/share",
    LEAN_REVIEW_RUNTIME_ADAPTER: "opencode",
    LEAN_REVIEW_CURRENT_MODEL: "provider-a/model-a",
  })
})
