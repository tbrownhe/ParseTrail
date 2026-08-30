const assert = require("node:assert/strict");
const test = require("node:test");

const { renderPluginRows } = require("../assets/js/plugins.js");

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.textContent = "";
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = [...children];
    }

    set innerHTML(_value) {
        throw new Error("plugin metadata reached an HTML parser");
    }
}

const fakeDocument = {
    createElement(tagName) {
        return new FakeElement(tagName);
    },
};

test("malicious plugin metadata is rendered only as inert cell text", () => {
    const tableBody = new FakeElement("tbody");
    const malicious = {
        COMPANY: '<img src=x onerror="globalThis.pluginMetadataExecuted=true">',
        STATEMENT_TYPE: "</td></tr><script>globalThis.pluginMetadataExecuted=true</script>",
        PLUGIN_NAME: 'name"><svg onload="globalThis.pluginMetadataExecuted=true">',
    };

    renderPluginRows(fakeDocument, tableBody, [malicious]);

    assert.equal(globalThis.pluginMetadataExecuted, undefined);
    assert.equal(tableBody.children.length, 1);
    assert.equal(tableBody.children[0].tagName, "tr");
    assert.deepEqual(
        tableBody.children[0].children.map((cell) => [cell.tagName, cell.textContent, cell.children.length]),
        [
            ["td", malicious.COMPANY, 0],
            ["td", malicious.STATEMENT_TYPE, 0],
            ["td", malicious.PLUGIN_NAME, 0],
        ],
    );
});
