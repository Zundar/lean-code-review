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
        return { data: { id: sessionID, model: { providerID, id: modelID } } }
      },
    },
    provider: {
      get: async ({ providerID: requested }) => {
        calls.push(["provider", requested])
        return { data: {
          id: requested,
          package: "@opencode/ai/providers/openai-compatible",
          settings: { baseURL: `https://${requested}.example/v1`, apiKey: "not-copied", transport: "websocket" },
          headers: { Authorization: "not-copied" },
        } }
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

test("binds the exact V2 session model and copies only safe metadata", async () => {
  const client = clientFor("session-a", "provider-a", "model-a")
  const binding = await bindSession(client, "session-a")

  assert.deepEqual(client.calls, [
    ["session", "session-a"],
    ["provider", "provider-a"],
    ["models"],
  ])
  assert.equal(binding.model, "provider-a/model-a")
  assert.deepEqual(binding.metadata, {
    provider: {
      id: "provider-a",
      package: "@opencode/ai/providers/openai-compatible",
      settings: { baseURL: "https://provider-a.example/v1", transport: "websocket" },
    },
    model: {
      id: "model-a",
      modelID: "upstream",
      providerID: "provider-a",
      name: "session-a",
      capabilities: { tools: true, input: ["text"], output: ["text"] },
      limit: { context: 200000, output: 64000 },
      variants: [{ id: "high", settings: { reasoningEffort: "high" } }],
    },
  }, "2.0.14")
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

test("supports an allowlisted native OpenAI provider definition", async () => {
  const client = clientFor("session-openai", "openai", "gpt-6-luna")
  client.provider.get = async () => ({ data: {
    id: "openai",
    package: "@opencode/ai/providers/openai",
    settings: { baseURL: "https://chatgpt.com/backend-api/codex", transport: "websocket" },
    headers: { authorization: "not-copied" },
  } })
  const binding = await bindSession(client, "session-openai")

  assert.equal(binding.model, "openai/gpt-6-luna")
  assert.deepEqual(binding.metadata.provider, {
    id: "openai",
    package: "@opencode/ai/providers/openai",
    settings: { baseURL: "https://chatgpt.com/backend-api/codex", transport: "websocket" },
  })
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
})

test("child launch receives only bound reviewer variables and nonsecret runtime context", () => {
  const env = reviewEnvironment({
    model: "provider-a/model-a",
    metadata: { provider: {}, model: {} },
  }, {
    PATH: "/safe/bin", HOME: "/home/user", XDG_DATA_HOME: "/home/user/.local/share",
    OPENAI_API_KEY: "do-not-copy", LEAN_REVIEW_CURRENT_MODEL: "stale",
  }, "2.0.14")

  assert.deepEqual(env, {
    PATH: "/safe/bin",
    HOME: "/home/user",
    XDG_DATA_HOME: "/home/user/.local/share",
    LEAN_REVIEW_RUNTIME_ADAPTER: "opencode",
    LEAN_REVIEW_CURRENT_MODEL: "provider-a/model-a",
    LEAN_REVIEW_OPENCODE_V2_METADATA: '{"provider":{},"model":{}}',
    LEAN_REVIEW_OPENCODE_CLI: process.execPath,
    LEAN_REVIEW_OPENCODE_VERSION: "2.0.14",
  })
})
