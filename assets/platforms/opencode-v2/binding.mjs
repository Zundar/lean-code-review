function data(value) {
  return value && typeof value === "object" && "data" in value ? value.data : value
}

function identifier(value) {
  return typeof value === "string" && value.length > 0 && !/[\s\0]/u.test(value)
}

function fail(message) {
  throw new Error(`lean-review OpenCode V2: ${message}`)
}

export async function bindSession(client, sessionID) {
  if (!identifier(sessionID)) fail("session identity is unavailable")
  const session = data(await client.session.get({ sessionID }))
  if (!session || session.id !== sessionID || !session.model
      || !identifier(session.model.providerID) || !identifier(session.model.id)) {
    fail("current session model is missing or ambiguous")
  }
  const providerID = session.model.providerID
  const modelID = session.model.id
  const models = data(await client.model.list())
  if (!Array.isArray(models)) fail("V2 model catalog is unavailable")
  const matching = models.filter(model => model?.providerID === providerID && model?.id === modelID)
  if (matching.length !== 1) fail("current session model is missing or ambiguous")
  if (session.model.variant && !matching[0].variants?.some(item => item.id === session.model.variant)) {
    fail("current session variant is unavailable")
  }
  return {
    sessionID,
    model: `${providerID}/${modelID}`,
    variant: session.model.variant,
    providerID,
    modelID,
  }
}

export function reviewEnvironment(binding, source = process.env) {
  const env = {}
  for (const key of ["PATH", "HOME", "XDG_DATA_HOME", "LANG", "LC_ALL", "TMPDIR"]) {
    if (source[key] !== undefined) env[key] = source[key]
  }
  env.LEAN_REVIEW_RUNTIME_ADAPTER = "opencode"
  env.LEAN_REVIEW_CURRENT_MODEL = binding.model
  return env
}

export { fail }
