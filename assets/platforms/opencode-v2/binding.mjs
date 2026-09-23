const MODEL_FIELDS = ["id", "modelID", "providerID", "name", "capabilities", "limit", "variants"]

function data(value) {
  return value && typeof value === "object" && "data" in value ? value.data : value
}

function identifier(value) {
  return typeof value === "string" && value.length > 0 && !/[\s\0]/u.test(value)
}

function fail(message) {
  throw new Error(`lean-review OpenCode V2: ${message}`)
}

function metadataFor(provider, model, current) {
  if (!provider || provider.id !== current.providerID || !model || model.providerID !== provider.id
      || model.id !== current.id || !identifier(model.id)) {
    fail("session provider/model metadata is missing or ambiguous")
  }
  const settings = provider.settings
  if (!new Set(["@opencode/ai/providers/openai-compatible", "@opencode/ai/providers/openai"])
      .has(provider.package) || !settings || typeof settings.baseURL !== "string"
      || !settings.baseURL.startsWith("https://") || settings.baseURL.includes("?")
      || settings.baseURL.includes("#") || settings.baseURL.includes("@")) {
    fail("selected V2 provider package or endpoint is unsupported")
  }
  const safeProvider = {
    id: provider.id,
    package: provider.package,
    settings: { baseURL: settings.baseURL },
  }
  if (settings.provider !== undefined) safeProvider.settings.provider = settings.provider
  if (settings.transport !== undefined) safeProvider.settings.transport = settings.transport

  const safeModel = {}
  for (const key of MODEL_FIELDS) {
    if (model[key] !== undefined) safeModel[key] = model[key]
  }
  return { provider: safeProvider, model: safeModel }
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
  const [providerResult, modelsResult] = await Promise.all([
    client.provider.get({ providerID }),
    client.model.list(),
  ])
  const provider = data(providerResult)
  const models = data(modelsResult)
  if (!Array.isArray(models)) fail("V2 model catalog is unavailable")
  const matching = models.filter(model => model?.providerID === providerID && model?.id === modelID)
  if (matching.length !== 1) fail("current session model is missing or ambiguous")
  return {
    sessionID,
    model: `${providerID}/${modelID}`,
    metadata: metadataFor(provider, matching[0], session.model),
  }
}

export function reviewEnvironment(binding, source = process.env, version) {
  const env = {}
  for (const key of ["PATH", "HOME", "XDG_DATA_HOME", "LANG", "LC_ALL", "TMPDIR"]) {
    if (source[key] !== undefined) env[key] = source[key]
  }
  env.LEAN_REVIEW_RUNTIME_ADAPTER = "opencode"
  env.LEAN_REVIEW_CURRENT_MODEL = binding.model
  env.LEAN_REVIEW_OPENCODE_V2_METADATA = JSON.stringify(binding.metadata)
  env.LEAN_REVIEW_OPENCODE_CLI = process.execPath
  env.LEAN_REVIEW_OPENCODE_VERSION = version
  return env
}

export { fail, metadataFor }
