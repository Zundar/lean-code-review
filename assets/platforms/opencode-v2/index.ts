import { spawn } from "node:child_process"
import { Plugin } from "@opencode/plugin"

import { bindSession, reviewEnvironment } from "./binding.mjs"

const MAX_OUTPUT = 1024 * 1024
const TIMEOUT_MS = 900_000

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
  return new Promise((resolve, reject) => {
    const child = spawn("lean-review", args, { cwd, env, stdio: ["ignore", "pipe", "ignore"] })
    let output = ""
    let overflow = false
    child.stdout.setEncoding("utf8")
    child.stdout.on("data", (chunk: string) => {
      if (overflow) return
      output += chunk
      if (Buffer.byteLength(output, "utf8") > MAX_OUTPUT) {
        overflow = true
        child.kill("SIGKILL")
      }
    })
    const timeout = setTimeout(() => child.kill("SIGKILL"), TIMEOUT_MS)
    child.once("error", error => {
      clearTimeout(timeout)
      reject(error)
    })
    child.once("close", (code, signal) => {
      clearTimeout(timeout)
      if (overflow) {
        reject(new Error("lean-review OpenCode V2: output limit exceeded"))
      } else if (code !== 0) {
        reject(new Error(output.trim() || `lean-review exited with ${signal ?? code}`))
      } else {
        resolve(output.trim())
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
