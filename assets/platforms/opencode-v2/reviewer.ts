import { constants } from "node:fs"
import { open, opendir, realpath, stat, lstat } from "node:fs/promises"
import path from "node:path"
import { Plugin } from "@opencode/plugin"

const RESTRICTED_COMPONENTS = new Set(["secrets", "credentials", "auth", ".ssh", ".git"])
const RESTRICTED_FILES = new Set([
  ".env", ".netrc", ".npmrc", ".pypirc", "auth-profiles.json", "auth.json",
  "credential.json", "credentials.json", "token.json", "tokens.json",
])
const MAX_FILE_BYTES = 1024 * 1024
const MAX_LINE_CHARS = 500

function fail(message: string): never {
  throw new Error(`lean-review-tools: ${message}`)
}

function inside(root: string, target: string): string {
  const relative = path.relative(root, target)
  if (path.isAbsolute(relative) || relative === ".." || relative.startsWith(`..${path.sep}`)) {
    fail("path is outside the project worktree")
  }
  return relative
}

function restricted(relative: string): boolean {
  const parts = relative.split(path.sep).filter(Boolean).map(part => part.toLowerCase())
  const basename = parts.at(-1) ?? ""
  if (basename === ".env.example") return parts.slice(0, -1).some(part => RESTRICTED_COMPONENTS.has(part))
  return parts.some(part => RESTRICTED_COMPONENTS.has(part)) || RESTRICTED_FILES.has(basename)
    || basename.startsWith(".env.") || basename.endsWith(".auth.json")
}

async function targetPath(requested: string, configured: string | undefined): Promise<{ root: string; target: string }> {
  if (!configured || path.isAbsolute(requested)) fail("target repository or relative path is missing")
  const root = await realpath(configured)
  if (root === path.parse(root).root) fail("filesystem-root worktrees are not allowed")
  const lexical = path.resolve(root, requested)
  inside(root, lexical)
  let walked = root
  for (const part of path.relative(root, lexical).split(path.sep).filter(Boolean)) {
    walked = path.join(walked, part)
    if ((await lstat(walked)).isSymbolicLink()) fail("symlinks are not allowed")
  }
  const target = await realpath(lexical)
  const relative = inside(root, target)
  if (restricted(relative)) fail("restricted path")
  return { root, target }
}

async function read(input: { path: string; offset?: number; limit?: number }, repo?: string): Promise<string> {
  const { target } = await targetPath(input.path, repo)
  const handle = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW)
  try {
    const info = await handle.stat()
    if (!info.isFile() || info.size > MAX_FILE_BYTES) fail("not a bounded regular file")
    const content = await handle.readFile()
    if (content.includes(0)) fail("binary file")
    const lines = content.toString("utf8").split(/\r?\n/u)
    const offset = input.offset ?? 0
    const limit = input.limit ?? 200
    return JSON.stringify({ offset, total: lines.length,
      lines: lines.slice(offset, offset + limit).map(line => line.slice(0, 2000)) })
  } finally {
    await handle.close()
  }
}

async function list(input: { path: string }, repo?: string): Promise<string> {
  const { root, target } = await targetPath(input.path, repo)
  if (!(await stat(target)).isDirectory()) fail("list target is not a directory")
  const rows: string[] = []
  let omitted = 0
  let seen = 0
  const directory = await opendir(target)
  for await (const entry of directory) {
    if (++seen > 256) fail("directory exceeds 256 entries; choose a narrower path")
    const relative = inside(root, path.join(target, entry.name))
    if (entry.isSymbolicLink() || restricted(relative)) {
      omitted += 1
      continue
    }
    const kind = entry.isDirectory() ? "directory" : entry.isFile() ? "file" : "other"
    rows.push(`${kind}\t${JSON.stringify(entry.name)}`)
  }
  rows.sort()
  return [`lean-review-tools.v2 list`, ...rows, `omitted=${omitted}`].join("\n")
}

async function grep(input: { path: string; query: string; case_sensitive?: boolean }, repo?: string): Promise<string> {
  if (!input.query || input.query.length > 256) fail("literal search query must be 1-256 characters")
  const { root, target } = await targetPath(input.path, repo)
  const matches: string[] = []
  let files = 0
  let visited = 0
  let omitted = 0
  let truncated = false
  const pending: Array<{ directory: string; depth: number }> = []
  const info = await stat(target)
  if (info.isDirectory()) pending.push({ directory: target, depth: 0 })
  else if (info.isFile()) pending.push({ directory: path.dirname(target), depth: 0 })
  else fail("grep target is not a file or directory")
  const needle = input.case_sensitive ? input.query : input.query.toLowerCase()

  if (info.isFile()) {
    const relative = inside(root, target)
    if (restricted(relative) || info.size > MAX_FILE_BYTES) fail("grep target is restricted or oversized")
    const content = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW)
    try {
      const bytes = await content.readFile()
      if (bytes.includes(0)) fail("grep target is binary")
      for (const [index, line] of bytes.toString("utf8").split(/\r?\n/u).entries()) {
        const haystack = input.case_sensitive ? line : line.toLowerCase()
        if (haystack.includes(needle)) matches.push(`${relative}:${index + 1}:${line.slice(0, MAX_LINE_CHARS)}`)
        if (matches.length >= 100) { truncated = true; break }
      }
      files = 1
    } finally {
      await content.close()
    }
  } else {
    while (pending.length && !truncated) {
      const current = pending.pop()!
      const directory = await opendir(current.directory)
      for await (const entry of directory) {
        if (++visited > 512) fail("search exceeds 512 entries; choose a narrower path")
        const child = path.join(current.directory, entry.name)
        const relative = inside(root, child)
        if (entry.isSymbolicLink() || restricted(relative)) { omitted += 1; continue }
        if (entry.isDirectory()) {
          if (current.depth < 8) pending.push({ directory: child, depth: current.depth + 1 })
          else omitted += 1
          continue
        }
        if (!entry.isFile()) continue
        const handle = await open(child, constants.O_RDONLY | constants.O_NOFOLLOW)
        try {
          const file = await handle.stat()
          if (file.size > MAX_FILE_BYTES) { omitted += 1; continue }
          const bytes = await handle.readFile()
          if (bytes.includes(0)) { omitted += 1; continue }
          for (const [index, line] of bytes.toString("utf8").split(/\r?\n/u).entries()) {
            const haystack = input.case_sensitive ? line : line.toLowerCase()
            if (haystack.includes(needle)) matches.push(`${relative}:${index + 1}:${line.slice(0, MAX_LINE_CHARS)}`)
            if (matches.length >= 100) { truncated = true; break }
          }
        } finally {
          await handle.close()
        }
        files += 1
        if (files > 512) fail("search exceeds 512 files; choose a narrower path")
        if (truncated) break
      }
    }
  }
  return [`lean-review-tools.v2 grep`, ...matches,
    `files=${files} matches=${matches.length} omitted=${omitted} truncated=${truncated}`].join("\n")
}

const schemas = {
  read: { type: "object", properties: {
    path: { type: "string", minLength: 1, maxLength: 512 },
    offset: { type: "integer", minimum: 0 },
    limit: { type: "integer", minimum: 1, maximum: 400 },
  }, required: ["path"], additionalProperties: false },
  list: { type: "object", properties: { path: { type: "string", minLength: 1, maxLength: 512 } },
    required: ["path"], additionalProperties: false },
  grep: { type: "object", properties: {
    path: { type: "string", minLength: 1, maxLength: 512 },
    query: { type: "string", minLength: 1, maxLength: 256 },
    case_sensitive: { type: "boolean" },
  }, required: ["path", "query"], additionalProperties: false },
}

export async function registerReviewerTools(ctx: any, repoForSession: (sessionID: string) => string | undefined) {
    await ctx.tool.transform(editor => {
      editor.namespace({ name: "lean_review", description: "Bounded read-only review tools" })
      editor.add({ name: "read", description: "Read a bounded project file, excluding secrets and symlinks.",
        input: schemas.read, options: { namespace: "lean_review" },
        execute: async (input, context) => ({ content: await read(input as { path: string; offset?: number; limit?: number }, repoForSession(context.sessionID)) }) })
      editor.add({ name: "list", description: "List a project directory without restricted entries or symlinks.",
        input: schemas.list, options: { namespace: "lean_review" },
        execute: async (input, context) => ({ content: await list(input as { path: string }, repoForSession(context.sessionID)) }) })
      editor.add({ name: "grep", description: "Search bounded project files for literal text without secrets.",
        input: schemas.grep, options: { namespace: "lean_review" },
        execute: async (input, context) => ({ content: await grep(input as { path: string; query: string; case_sensitive?: boolean }, repoForSession(context.sessionID)) }) })
    })
}

export const LeanReviewV2Tools = Plugin.define({
  id: "lean-review.opencode-v2-tools",
  setup(ctx) {
    return registerReviewerTools(ctx, () => process.env.LEAN_REVIEW_TARGET_REPO)
  },
})

export default LeanReviewV2Tools
