const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const test = require("node:test")
const vm = require("node:vm")

const script = fs.readFileSync(
  path.join(__dirname, "..", "assets", "js", "config.js"),
  "utf8",
)

function loadConfig(runtimeConfig) {
  const listeners = new Map()
  const githubLink = {}
  const accountLink = {}
  const document = {
    addEventListener(name, callback) {
      listeners.set(name, callback)
    },
    querySelectorAll(selector) {
      if (selector === ".nav-github") return [githubLink]
      if (selector === ".nav-login") return [accountLink]
      return []
    },
  }
  const window = { __PARSETRAIL_CONFIG__: runtimeConfig }

  vm.runInNewContext(script, { URL, document, window })
  listeners.get("DOMContentLoaded")()

  return { accountLink, config: window.ParseTrailConfig, githubLink }
}

test("runtime URLs are validated, normalized, and applied to navigation", () => {
  const loaded = loadConfig({
    apiBaseUrl: "https://api.example.com/api/v1/",
    accountUrl: "https://dashboard.example.com/",
    githubUrl: "https://github.com/example/project/",
  })

  assert.equal(loaded.config.apiBaseUrl, "https://api.example.com/api/v1")
  assert.equal(loaded.accountLink.href, "https://dashboard.example.com")
  assert.equal(loaded.githubLink.href, "https://github.com/example/project")
})

test("unsafe runtime URLs fail closed", () => {
  assert.throws(
    () =>
      loadConfig({
        apiBaseUrl: "javascript:alert(1)",
        accountUrl: "https://dashboard.example.com",
        githubUrl: "https://github.com/example/project",
      }),
    /Invalid ParseTrail runtime URL/,
  )
})
