import { execFileSync } from "node:child_process"

import type { Plugin } from "@opencode-ai/plugin"

/** Add the V1 host identity to the existing shell.env caller binding. */
export const LeanReviewOpenCodeV1Identity: Plugin = async () => ({
  "shell.env": async (_input, output) => {
    const executable = process.execPath
    const version = execFileSync(executable, ["--version"], {
      encoding: "utf8",
      timeout: 10_000,
    }).trim()
    output.env.LEAN_REVIEW_OPENCODE_CLI = executable
    output.env.LEAN_REVIEW_OPENCODE_VERSION = version
  },
})

export default LeanReviewOpenCodeV1Identity
