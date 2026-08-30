(function exposePluginTable(globalScope) {
    "use strict";

    function renderPluginRows(documentObject, tableBody, plugins) {
        tableBody.replaceChildren();
        for (const plugin of plugins) {
            const row = documentObject.createElement("tr");
            for (const value of [plugin.COMPANY, plugin.STATEMENT_TYPE, plugin.PLUGIN_NAME]) {
                const cell = documentObject.createElement("td");
                cell.textContent = value == null ? "" : String(value);
                row.appendChild(cell);
            }
            tableBody.appendChild(row);
        }
    }

    const api = Object.freeze({ renderPluginRows });
    globalScope.ParseTrailPluginTable = api;
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
})(typeof window === "undefined" ? globalThis : window);
