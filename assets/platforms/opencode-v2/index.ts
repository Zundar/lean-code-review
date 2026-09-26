import { spawn } from "node:child_process"
import { Plugin } from "@opencode/plugin"

import { bindSession, reviewEnvironment } from "./binding.mjs"
import { registerReviewerTools } from "./reviewer.ts"

const MAX_OUTPUT = 1024 * 1024
const TIMEOUT_MS = 900_000
const SECRET_KEY = /(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)(?:$|[_-])/iu

function redact(value: string): string {
  return value
    .replace(/(--authorization(?:=|\s+))(?:["']?(?:bearer|basic)\s+[^"'\r\n]+["']?)/giu, "$1[REDACTED]")
    .replace(/(--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|token|secret|password|authorization)(?:=|\s+))\S+/giu, "$1[REDACTED]")
    .replace(/\b(authorization)\s*:\s*(?:bearer|basic)\s+\S+/giu, "$1: [REDACTED]")
    .replace(/(invalid choice:\s+)["'][^\r\n]*?["'](\s+\(choose from\s+[^)\r\n]*\))/giu, "$1[REDACTED]$2")
    .replace(/\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)\s*[:=]\s*([^\s,'"}\]]+)/giu, "$1=[REDACTED]")
    .replace(/https?:\/\/[^/@\s]+:[^/@\s]+@/giu, "https://[REDACTED]@")
    .replace(/([?&](?:key|token|secret|password|authorization)=)[^&\s]+/giu, "$1[REDACTED]")
    .slice(0, 4096)
}

function safeStructuredOutput(output: string): string | undefined {
  try {
    const value: unknown = JSON.parse(output)
    if (!value || typeof value !== "object" || Array.isArray(value)
        || typeof (value as { verdict?: unknown }).verdict !== "string") return
    const scrub = (item: unknown): unknown => {
      if (Array.isArray(item)) return item.map(scrub)
      if (!item || typeof item !== "object") return typeof item === "string" ? redact(item) : item
      return Object.fromEntries(Object.entries(item).map(([key, child]) => [
        key,
        SECRET_KEY.test(key.replace(/([a-z0-9])([A-Z])/gu, "$1_$2")) ? "[REDACTED]" : scrub(child),
      ]))
    }
    return JSON.stringify(scrub(value))
  } catch {
    return
  }
}

export function commandArguments(prompt: { text?: string }): string[] {
  const text = prompt.text?.trim()
  if (!text) throw new Error("lean-review OpenCode V2: pass generic lean-review CLI arguments")

  const args: string[] = []
  let token = ""
  let quote: "'" | '"' | undefined
  let escaped = false
  let started = false
  for (const char of text) {
    if (escaped) {
      token += char
      escaped = false
      continue
    }
    if (char === "\\" && quote !== "'") {
      escaped = true
      started = true
      continue
    }
    if (quote) {
      if (char === quote) quote = undefined
      else token += char
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      started = true
      continue
    }
    if (/\s/u.test(char)) {
      if (started) args.push(token)
      token = ""
      started = false
      continue
    }
    if (char === "`" || char === "$") {
      throw new Error("lean-review OpenCode V2: shell expansion is not supported")
    }
    token += char
    started = true
  }
  if (escaped || quote) throw new Error("lean-review OpenCode V2: malformed CLI quoting")
  if (started) args.push(token)
  if (args.some(arg => arg.includes("\0"))) throw new Error("lean-review OpenCode V2: malformed CLI argument")
  if (args.some(arg => arg === "--model" || arg === "-m" || arg.startsWith("--model="))) {
    throw new Error("lean-review OpenCode V2: model is bound to the current session")
  }
  return args
}

function runReview(args: string[], env: Record<string, string>, cwd: string,
                   input = "", raw = false): Promise<string> {
  return new Promise(resolve => {
    let child
    try {
      child = spawn("lean-review", args, { cwd, env, stdio: ["pipe", "pipe", "pipe"] })
    } catch {
      resolve("lean-review could not start")
      return
    }
    let output = ""
    let errorOutput = ""
    let outputBytes = 0
    let overflow = false
    let settled = false
    let timeout: ReturnType<typeof setTimeout>
    const finish = (result: string) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      resolve(result)
    }
    const capture = (stream: NodeJS.ReadableStream, append: (chunk: string) => void) => {
      stream.setEncoding("utf8")
      stream.on("data", (chunk: string) => {
        if (overflow || settled) return
        const bytes = Buffer.byteLength(chunk, "utf8")
        if (outputBytes + bytes > MAX_OUTPUT) {
          overflow = true
          child.kill("SIGKILL")
          finish("lean-review OpenCode V2: output limit exceeded")
        } else {
          outputBytes += bytes
          append(chunk)
        }
      })
    }
    capture(child.stdout, chunk => { output += chunk })
    capture(child.stderr, chunk => { errorOutput += chunk })
    timeout = setTimeout(() => {
      child.kill("SIGKILL")
      finish("lean-review OpenCode V2: timed out")
    }, TIMEOUT_MS)
    child.once("error", error => {
      finish(`lean-review could not start: ${redact(error.code ?? "spawn failed")}`)
    })
    child.once("close", (code, signal) => {
      if (overflow) {
        finish("lean-review OpenCode V2: output limit exceeded")
      } else {
        const trimmed = output.trim()
        const structured = code === 0 || code === 1 || code === 2
          ? safeStructuredOutput(trimmed)
          : undefined
        if (raw && code === 0) {
          finish(trimmed)
        } else if (structured) {
          finish(structured)
        } else if (code === 0) {
          finish(redact(trimmed))
        } else {
          const details = redact([trimmed, errorOutput.trim()].filter(Boolean).join("\n"))
          finish(`lean-review exited with ${signal ?? code}${details ? `\n${details}` : ""}`)
        }
      }
    })
    child.stdin.on("error", () => {}) // A failed child may close stdin before the packet is written.
    child.stdin.end(input)
  })
}

const unwrap = (value: any) => value && typeof value === "object" && "data" in value ? value.data : value
const allowed = ["execute", "lean_review_read", "lean_review_list", "lean_review_grep"]
const permissions = [
  { action: "*", resource: "*", effect: "deny" },
  ...allowed.map(action => ({ action, resource: "*", effect: "allow" })),
]
// The context hook replaces every ambient system part, including project/global instructions.
const reviewerCatalog = `# Code Mode
Use the execute tool to call only the bounded tools listed below. They work only inside execute.
The catalog is complete. Do not guess tool names.

## Available tools

- lean_review (3 tools) // Bounded read-only review tools
  - tools.lean_review.read({path: string, offset?: number, limit?: number}): Promise<string | null>
  - tools.lean_review.list({path: string}): Promise<string | null>
  - tools.lean_review.grep({path: string, query: string, case_sensitive?: boolean}): Promise<string | null>`

function sameModel(actual: any, expected: any): boolean {
  return actual?.providerID === expected.providerID && actual?.id === expected.id
    && actual?.variant === expected.variant
}

function deniedExceptReviewer(rules: any[]): boolean {
  if (!Array.isArray(rules) || !rules.length) return false
  const boundary = rules.findLastIndex(rule => rule.action === "*" && rule.resource === "*" && rule.effect === "deny")
  if (boundary < 0 || rules.slice(boundary + 1).some(rule => rule.effect === "allow"
      && (!allowed.includes(rule.action) || rule.resource !== "*"))) return false
  const effect = (action: string) => rules.filter(rule => rule.resource === "*"
    && (rule.action === "*" || rule.action === action)).at(-1)?.effect
  return effect("*") === "deny" && allowed.every(action => effect(action) === "allow")
    && ["shell", "edit", "subagent", "read", "glob", "grep", "skill", "webfetch", "websearch", "question"]
      .every(action => effect(action) === "deny")
}

async function reviewInService(ctx: any, sessionID: string, prompt: any,
                               bindings: Map<string, { repo: string; model: any; agent: string; system: string; checked: boolean }>): Promise<string> {
  const binding = await bindSession(ctx, sessionID)
  const args = commandArguments(prompt)
  const depth = args[args.indexOf("--depth") + 1]
  if (!["lite", "strict"].includes(depth)) throw new Error("lean-review OpenCode V2: invalid depth")
  const agent = `spec-reviewer-${depth}`
  const model = { providerID: binding.providerID, id: binding.modelID,
    ...(binding.variant ? { variant: binding.variant } : {}) }
  const env = reviewEnvironment(binding, process.env)
  const prepared = JSON.parse(await runReview(["v2-prepare", ...args], env, ctx.location.directory, "", true))
  if (prepared.model !== binding.model || !prepared.runtime || !prepared.repo) {
    throw new Error("lean-review OpenCode V2: frozen packet does not match the caller")
  }
  const profile = unwrap(await ctx.agent.get({ agentID: agent }))
  if (profile?.id !== agent || profile.mode !== "primary" || !deniedExceptReviewer(profile.permissions)
      || !prepared.agent_system || profile.system !== prepared.agent_system) {
    throw new Error("lean-review OpenCode V2: dedicated reviewer agent is unavailable or unsafe")
  }
  const created = unwrap(await ctx.session.create({ title: `Lean Review ${depth}`, agent, model,
    location: { directory: ctx.location.directory }, permissions }))
  if (!created?.id || created.id === sessionID) throw new Error("lean-review OpenCode V2: reviewer session is not distinct")
  bindings.set(created.id, { repo: prepared.repo, model, agent, system: prepared.agent_system, checked: false })
  try {
    const selected = unwrap(await ctx.session.get({ sessionID: created.id }))
    const catalog = unwrap(await ctx.tool.list())
    const models = unwrap(await ctx.model.list())
    if (selected?.id !== created.id || selected.agent !== agent || !sameModel(selected.model, model)
        || JSON.stringify(selected.permissions) !== JSON.stringify(permissions)
        || !deniedExceptReviewer([...profile.permissions, ...selected.permissions])
        || !Array.isArray(catalog) || !allowed.slice(1).every(id => catalog.some((tool: any) => tool.id === id))
        || !Array.isArray(models) || models.filter((item: any) => item.providerID === model.providerID && item.id === model.id).length !== 1
        || (model.variant && !models.find((item: any) => item.providerID === model.providerID && item.id === model.id)
          ?.variants?.some((item: any) => item.id === model.variant))) {
      throw new Error("lean-review OpenCode V2: reviewer identity, permissions or tools failed readback")
    }
    await ctx.session.prompt({ sessionID: created.id, text: prepared.packet })
    await ctx.session.wait({ sessionID: created.id })
    if (!bindings.get(created.id)?.checked) throw new Error("lean-review OpenCode V2: effective tool preflight did not run")
    const messages = unwrap(await ctx.session.context({ sessionID: created.id }))
    const replies = messages.filter((item: any) => item.type === "assistant" && item.finish === "stop")
    const last = replies.at(-1)
    if (!last || messages.some((item: any) => item.type === "assistant" && !sameModel(item.model, model))) {
      throw new Error("lean-review OpenCode V2: reviewer steps did not finish on bound model")
    }
    const verdict = last.content.filter((part: any) => part.type === "text").map((part: any) => part.text).join("\n").trim()
    const steps = messages.filter((item: any) => item.type === "assistant" && item.finish)
    if (!steps.length || steps.some((item: any) => !Number.isInteger(item.tokens?.input)
        || !Number.isInteger(item.tokens?.output) || !Number.isInteger(item.tokens?.cache?.read))) {
      throw new Error("lean-review OpenCode V2: model-backed usage is missing")
    }
    const usage = { calls: steps.length,
      input_tokens: steps.reduce((sum: number, item: any) => sum + item.tokens.input, 0),
      cached_input_tokens: steps.reduce((sum: number, item: any) => sum + item.tokens.cache.read, 0),
      output_tokens: steps.reduce((sum: number, item: any) => sum + item.tokens.output, 0) }
    return await runReview(["v2-finish", prepared.runtime], env, ctx.location.directory,
      JSON.stringify({ session: created.id, verdict, variant: model.variant, usage }))
  } finally {
    bindings.delete(created.id)
  }
}

export const LeanReviewV2 = Plugin.define({
  id: "lean-review.opencode-v2",
  async setup(ctx) {
    const bindings = new Map<string, { repo: string; model: any; agent: string; system: string; checked: boolean }>()
    await registerReviewerTools(ctx, sessionID => bindings.get(sessionID)?.repo)
    await ctx.session.hook("context", event => {
      const review = bindings.get(event.sessionID)
      if (!review) return
      if (!Array.isArray(event.system) || !event.system.some(part => part.type === "text" && part.text === review.system)) {
        throw new Error("lean-review OpenCode V2: canonical reviewer instructions are missing")
      }
      // Do not forward ambient project/global instructions, references or platform worktree guidance.
      event.system.splice(0, event.system.length, { type: "text", text: review.system },
        { type: "text", text: reviewerCatalog })
      const catalog = event.system.map(part => part.text ?? "").join("\n")
      const tools = Object.keys(event.tools)
      const codeMode = catalog.split("## Available tools")[1]?.split("\n\n#")[0] ?? ""
      const namespaces = [...codeMode.matchAll(/^- ([\w-]+) \((\d+) tools?\)/gm)]
      const names = [...codeMode.matchAll(/tools\.lean_review\.(read|list|grep)\b/g)].map(match => match[1])
      if (event.agent !== review.agent || !sameModel(event.model, review.model)
          || tools.length !== 1 || tools[0] !== "execute"
          || !catalog.includes("The catalog is complete")
          || namespaces.length !== 1 || namespaces[0][1] !== "lean_review" || namespaces[0][2] !== "3"
          || new Set(names).size !== 3 || /<mcp_instructions>/u.test(catalog)) {
        throw new Error("lean-review OpenCode V2: effective reviewer catalog is unsafe")
      }
      review.checked = true
    })
    await ctx.command.transform(editor => {
      editor.add({
        name: "lean-review",
        description: "Run the isolated lean-review launcher for this exact V2 session.",
        execute: async ({ sessionID, prompt }) => {
          let result
          try {
            result = await reviewInService(ctx, sessionID, prompt, bindings)
          } catch (error) {
            result = JSON.stringify({ verdict: "BLOCKED", reason: redact(String(error)) })
          }
          await ctx.session.synthetic({ sessionID, text: result })
        },
      })
    })
  },
})

export default LeanReviewV2
