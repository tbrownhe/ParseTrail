import { spawnSync } from "node:child_process"
import { writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"

const backendDirectory = fileURLToPath(new URL("../backend/", import.meta.url))
const outputPath = fileURLToPath(new URL("./openapi.json", import.meta.url))
const exportCommand = [
  "import app.main",
  "import json",
  "print(json.dumps(app.main.app.openapi()))",
].join("; ")

const result = spawnSync(
  "uv",
  ["run", "--frozen", "python", "-c", exportCommand],
  {
    cwd: backendDirectory,
    encoding: "utf8",
  },
)

if (result.error) {
  throw result.error
}
if (result.status !== 0) {
  throw new Error(
    result.stderr || `OpenAPI export failed with ${result.status}`,
  )
}

const document = JSON.parse(result.stdout)
for (const path of Object.values(document.paths ?? {})) {
  for (const operation of Object.values(path)) {
    const tag = operation?.tags?.[0]
    if (tag && operation.operationId?.startsWith(`${tag}-`)) {
      operation.operationId = operation.operationId.slice(tag.length + 1)
    }
  }
}

await writeFile(outputPath, `${JSON.stringify(document, null, 2)}\n`, "utf8")
console.log(`Generated ${outputPath}`)
