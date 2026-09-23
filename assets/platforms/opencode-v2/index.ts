import { spawn } from "node:child_process"
import { Plugin } from "@opencode/plugin"

import { bindSession, reviewEnvironment } from "./binding.mjs"

const MAX_OUTPUT = 1024 * 1024
const TIMEOUT_MS = 900_000
const SECRET_KEY = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)/iu

function redact(value: string): string {
  return value
    .replace(/(--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|token|secret|password|authorization)(?:=|\s+))\S+/giu, "$1[REDACTED]")
    .replace(/\b(authorization)\s*:\s*(?:bearer|basic)\s+\S+/giu, "$1: [REDACTED]")
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
        SECRET_KEY.test(key) ? "[REDACTED]" : scrub(child),
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

function runReview(args: string[], env: Record<string, string>, cwd: string): Promise<string> {
  return new Promise(resolve => {
    let child
    try {
      child = spawn("lean-review", args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] })
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
        if (structured) {
          finish(structured)
        } else if (code === 0) {
          finish(redact(trimmed))
        } else {
          const details = redact([trimmed, errorOutput.trim()].filter(Boolean).join("\n"))
          finish(`lean-review exited with ${signal ?? code}${details ? `\n${details}` : ""}`)
        }
      }
    })
  })
}

export const LeanReviewV2 = Plugin.define({
  id: "lean-review.opencode-v2",
  async setup(ctx) {
    await ctx.command.transform(editor => {
      editor.add({
        name: "lean-review",
        description: "Run the isolated lean-review launcher for this exact V2 session.",
        execute: async ({ sessionID, prompt }) => {
          const binding = await bindSession(ctx, sessionID)
          const result = await runReview(
            commandArguments(prompt),
            reviewEnvironment(binding, process.env, ctx.app.version),
            ctx.location.directory,
          )
          await ctx.session.synthetic({ sessionID, text: result })
        },
      })
    })
  },
})

export default LeanReviewV2
