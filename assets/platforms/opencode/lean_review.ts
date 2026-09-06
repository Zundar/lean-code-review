import { constants } from "node:fs"
import { open, opendir, realpath, stat, lstat } from "node:fs/promises"
import path from "node:path"

import { tool, type ToolContext } from "@opencode-ai/plugin"

const MARKER = "lean-review-tools.v1"
const MAX_DEPTH = 8
const MAX_ENTRIES = 256
const MAX_FILES = 512
const MAX_VISITED_ENTRIES = 512
const MAX_FILE_BYTES = 1024 * 1024
const MAX_MATCHES = 100
const MAX_LINE_CHARS = 500

const RESTRICTED_COMPONENTS = new Set(["secrets", "credentials", "auth", ".ssh", ".git"])
const RESTRICTED_FILES = new Set([
  ".env",
  ".netrc",
  ".npmrc",
  ".pypirc",
  "auth-profiles.json",
  "auth.json",
  "credential.json",
  "credentials.json",
  "token.json",
  "tokens.json",
])

function fail(message: string): never {
  throw new Error(`lean-review-tools: ${message}`)
}

function isRestricted(relativePath: string): boolean {
  const parts = relativePath.split(path.sep).filter(Boolean).map((part) => part.toLowerCase())
  const basename = parts.at(-1) ?? ""
  if (basename === ".env.example") return parts.slice(0, -1).some((part) => RESTRICTED_COMPONENTS.has(part))
  return (
    parts.some((part) => RESTRICTED_COMPONENTS.has(part)) ||
    RESTRICTED_FILES.has(basename) ||
    basename.startsWith(".env.") ||
    basename.endsWith(".auth.json")
  )
}

function relativeInside(root: string, candidate: string): string {
  const relative = path.relative(root, candidate)
  if (relative === "") return relative
  if (path.isAbsolute(relative) || relative === ".." || relative.startsWith(`..${path.sep}`)) {
    fail("path is outside the project worktree")
  }
  return relative
}

async function worktreeRoot(context: ToolContext): Promise<string> {
  if (!(process.env.LEAN_REVIEW_TARGET_REPO || context.worktree)) fail("worktree is empty")
  const root = await realpath((process.env.LEAN_REVIEW_TARGET_REPO || context.worktree))
  if (root === path.parse(root).root) fail("filesystem-root worktrees are not allowed")
  return root
}

async function resolveTarget(context: ToolContext, requested: string): Promise<{ root: string; target: string }> {
  if (path.isAbsolute(requested)) fail("absolute paths are not allowed")
  const root = await worktreeRoot(context)
  const lexical = path.resolve(root, requested)
  relativeInside(root, lexical)
  let walked = root
  for (const part of path.relative(root, lexical).split(path.sep).filter(Boolean)) {
    walked = path.join(walked, part)
    if ((await lstat(walked)).isSymbolicLink()) fail("symlinks are not allowed")
  }
  const target = await realpath(lexical)
  const relative = relativeInside(root, target)
  if (isRestricted(relative)) fail("restricted path")
  return { root, target }
}

async function directoryEntries(root: string, target: string): Promise<string> {
  if (!(await stat(target)).isDirectory()) fail("list target is not a directory")
  const rows: string[] = []
  let omitted = 0
  let seen = 0
  const directory = await opendir(target)
  for await (const entry of directory) {
    seen += 1
    if (seen > MAX_ENTRIES) fail(`directory exceeds ${MAX_ENTRIES} entries; choose a narrower path`)
    const child = path.join(target, entry.name)
    const relative = relativeInside(root, child)
    if (entry.isSymbolicLink() || isRestricted(relative)) {
      omitted += 1
      continue
    }
    const kind = entry.isDirectory() ? "directory" : entry.isFile() ? "file" : "other"
    rows.push(`${kind}\t${JSON.stringify(entry.name)}`)
  }
  rows.sort()
  return [`${MARKER} list`, ...rows, `omitted=${omitted}`].join("\n")
}

type Match = { path: string; line: number; text: string }
type ScanResult = "scanned" | "restricted" | "not-file" | "oversized" | "binary"

async function scanFile(
  root: string,
  filename: string,
  query: string,
  caseSensitive: boolean,
  matches: Match[],
): Promise<ScanResult> {
  const resolved = await realpath(filename)
  const relative = relativeInside(root, resolved)
  if (isRestricted(relative)) return "restricted"
  const handle = await open(resolved, constants.O_RDONLY | constants.O_NOFOLLOW)
  try {
    const info = await handle.stat()
    if (!info.isFile()) return "not-file"
    if (info.size > MAX_FILE_BYTES) return "oversized"
    const content = await handle.readFile()
    if (content.includes(0)) return "binary"
    const needle = caseSensitive ? query : query.toLowerCase()
    for (const [index, rawLine] of content.toString("utf8").split(/\r?\n/u).entries()) {
      const haystack = caseSensitive ? rawLine : rawLine.toLowerCase()
      if (!haystack.includes(needle)) continue
      matches.push({ path: relative, line: index + 1, text: rawLine.slice(0, MAX_LINE_CHARS) })
      if (matches.length >= MAX_MATCHES) break
    }
    return "scanned"
  } finally {
    await handle.close()
  }
}

async function grepLiteral(
  root: string,
  target: string,
  query: string,
  caseSensitive: boolean,
): Promise<string> {
  const targetInfo = await stat(target)
  const matches: Match[] = []
  let omitted = 0
  let files = 0
  let visited = 0
  let truncated = false

  if (targetInfo.isFile()) {
    const result = await scanFile(root, target, query, caseSensitive, matches)
    if (result !== "scanned") fail(`grep target was not searched: ${result}`)
    files = 1
  } else if (targetInfo.isDirectory()) {
    const pending: Array<{ directory: string; depth: number }> = [{ directory: target, depth: 0 }]
    while (pending.length && !truncated) {
      const current = pending.pop()!
      const directory = await opendir(current.directory)
      for await (const entry of directory) {
        visited += 1
        if (visited > MAX_VISITED_ENTRIES) {
          fail(`search exceeds ${MAX_VISITED_ENTRIES} entries; choose a narrower path`)
        }
        const child = path.join(current.directory, entry.name)
        const relative = relativeInside(root, child)
        if (entry.isSymbolicLink() || isRestricted(relative)) {
          omitted += 1
          continue
        }
        if (entry.isDirectory()) {
          if (current.depth < MAX_DEPTH) pending.push({ directory: child, depth: current.depth + 1 })
          else omitted += 1
          continue
        }
        if (!entry.isFile()) continue
        const result = await scanFile(root, child, query, caseSensitive, matches)
        if (result !== "scanned") {
          omitted += 1
          continue
        }
        files += 1
        if (files > MAX_FILES) fail(`search exceeds ${MAX_FILES} files; choose a narrower path`)
        if (matches.length >= MAX_MATCHES) {
          truncated = true
          break
        }
      }
    }
  } else {
    fail("grep target is not a file or directory")
  }

  const rows = matches.map((match) => `${match.path}:${match.line}:${match.text}`)
  return [
    `${MARKER} grep`,
    ...rows,
    `files=${files} matches=${matches.length} omitted=${omitted} truncated=${truncated}`,
  ].join("\n")
}

export const list = tool({
  description: "List one project directory without following symlinks or revealing restricted entries.",
  args: {
    path: tool.schema.string().min(1).max(512).describe("Project-relative directory path"),
  },
  async execute(args, context) {
    const { root, target } = await resolveTarget(context, args.path)
    return directoryEntries(root, target)
  },
})

export const grep = tool({
  description: "Search project files for a bounded literal string without shell, regex, symlinks, or secrets.",
  args: {
    path: tool.schema.string().min(1).max(512).describe("Project-relative file or directory path"),
    query: tool.schema.string().min(1).max(256).describe("Literal text to find"),
    case_sensitive: tool.schema.boolean().default(false),
  },
  async execute(args, context) {
    const { root, target } = await resolveTarget(context, args.path)
    return grepLiteral(root, target, args.query, args.case_sensitive)
  },
})


export const read = tool({
  description: "Read a bounded text file inside the target repository, without secrets or symlinks.",
  args: {
    path: tool.schema.string().min(1).max(512).describe("Project-relative file path"),
    offset: tool.schema.number().int().min(0).default(0),
    limit: tool.schema.number().int().min(1).max(400).default(200),
  },
  async execute(args, context) {
    const { target } = await resolveTarget(context, args.path)
    const handle = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW)
    try {
      const info = await handle.stat()
      if (!info.isFile() || info.size > MAX_FILE_BYTES) fail("not a bounded regular file")
      const content = await handle.readFile()
      if (content.includes(0)) fail("binary file")
      const lines = content.toString("utf8").split(/\r?\n/u)
      const offset = args.offset ?? 0
      const limit = args.limit ?? 200
      return JSON.stringify({ offset, total: lines.length,
        lines: lines.slice(offset, offset + limit).map(line => line.slice(0, 2000)) })
    } finally {
      await handle.close()
    }
  },
})
