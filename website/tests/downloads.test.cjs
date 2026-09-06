const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { renderDownloads, loadDownloads } = require("../assets/js/downloads.js");

class Element {
    constructor(tagName) { this.tagName = tagName; this.children = []; this.textContent = ""; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...children) { this.children = children; }
    set innerHTML(_value) { throw new Error("Catalog data must not be parsed as HTML"); }
}
function fixture() {
    const container = new Element("div");
    return { container, document: { createElement: (tag) => new Element(tag), getElementById: () => container } };
}
function artifact(platform, overrides = {}) {
    return { platform, architecture: "x86_64", manifest_schema_version: 2, version: "1.4.0",
        file_name: `parsetrail_1.4.0_${platform}_setup${platform.startsWith("windows") ? ".exe" : ".dmg"}`,
        ...overrides };
}
function links(container) { return container.children.filter((element) => element.tagName === "a"); }

test("same-version Windows and Intel Mac releases get explicit separate links", () => {
    const { document, container } = fixture();
    renderDownloads(document, container, [artifact("macos-x86_64"), artifact("windows-x86_64")], "https://api.example/api/v1");
    assert.deepEqual(links(container).map((link) => [link.textContent, link.href]), [
        ["Download for Windows (x64)", "https://api.example/api/v1/clients/windows-x86_64/1.4.0"],
        ["Download for Intel Mac (x86_64)", "https://api.example/api/v1/clients/macos-x86_64/1.4.0"],
    ]);
});

test("old, ARM, and mismatched-architecture catalogs never advertise a download", () => {
    const { document, container } = fixture();
    renderDownloads(document, container, [artifact("win64"), artifact("macos"), artifact("macos-arm64"),
        artifact("windows-x86_64", { architecture: "arm64" }), artifact("macos-x86_64", { manifest_schema_version: 1 })], "https://api.example");
    assert.equal(links(container).length, 0);
    assert.match(container.children[0].textContent, /No supported installers/);
});

test("a partial catalog offers only its available supported target", () => {
    const { document, container } = fixture();
    renderDownloads(document, container, [artifact("macos-x86_64")], "https://api.example");
    assert.equal(links(container).length, 1);
    assert.match(links(container)[0].textContent, /Intel Mac/);
});

test("ambiguous, malformed and failed catalogs remove stale links", async () => {
    for (const payload of [null, [artifact("macos-x86_64"), artifact("macos-x86_64")],
        [artifact("windows-x86_64", { file_name: "wrong.exe" })],
        [artifact("windows-x86_64", { version: '<img src=x onerror="bad()">' })]]) {
        const { document, container } = fixture();
        container.appendChild(new Element("a"));
        await loadDownloads(document, async () => ({ ok: true, json: async () => payload }), "https://api.example");
        assert.equal(links(container).length, 0);
        assert.match(container.children[0].textContent, /Failed to load/);
    }
    const { document, container } = fixture();
    await loadDownloads(document, async () => ({ ok: false, status: 503 }), "https://api.example");
    assert.match(container.children[0].textContent, /Failed to load/);
});

test("the download page boots the selector without guessing architecture from the browser", async () => {
    const html = fs.readFileSync(`${__dirname}/../download.html`, "utf8");
    assert.match(html, /src="assets\/js\/downloads.js" defer/);
    const { document, container } = fixture();
    let ready;
    document.addEventListener = (event, callback) => { assert.equal(event, "DOMContentLoaded"); ready = callback; };
    const window = { document, ParseTrailConfig: { apiBaseUrl: "https://api.example/api/v1" },
        fetch: async (url) => {
            assert.equal(url, "https://api.example/api/v1/clients/");
            return { ok: true, json: async () => [artifact("macos-x86_64")] };
        } };
    Object.defineProperty(window, "navigator", { get() { throw new Error("Browser platform is not a CPU guarantee"); } });
    vm.runInNewContext(fs.readFileSync(`${__dirname}/../assets/js/downloads.js`, "utf8"), { window });
    await ready();
    assert.equal(links(container).length, 1);
});
