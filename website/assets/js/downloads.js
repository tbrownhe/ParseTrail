(function (root) {
    "use strict";

    const targets = Object.freeze({
        "windows-x86_64": { label: "Windows (x64)", suffix: ".exe" },
        "macos-x86_64": { label: "Intel Mac (x86_64)", suffix: ".dmg" },
    });

    function renderDownloads(document, container, installers, apiBaseUrl) {
        if (!Array.isArray(installers)) throw new Error("Invalid installer catalog");
        const selected = new Map();
        for (const installer of installers) {
            if (!installer || !Object.hasOwn(targets, installer.platform)) continue;
            if (installer.architecture !== "x86_64" || installer.manifest_schema_version !== 2) continue;
            const target = targets[installer.platform];
            if (typeof installer.version !== "string" ||
                !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(installer.version) ||
                installer.file_name !== `parsetrail_${installer.version}_${installer.platform}_setup${target.suffix}`) {
                throw new Error("Installer identity disagrees with its target");
            }
            if (selected.has(installer.platform)) throw new Error("Ambiguous installer target");
            selected.set(installer.platform, installer);
        }
        container.replaceChildren();
        const guidance = document.createElement("p");
        guidance.textContent = selected.size
            ? "Choose the installer matching your computer. The Mac release requires an Intel processor."
            : "No supported installers are currently available. Please try again later.";
        container.appendChild(guidance);
        for (const [platform, target] of Object.entries(targets)) {
            const installer = selected.get(platform);
            if (!installer) continue;
            const link = document.createElement("a");
            link.href = `${apiBaseUrl.replace(/\/$/, "")}/clients/${platform}/${encodeURIComponent(installer.version)}`;
            link.textContent = `Download for ${target.label}`;
            link.className = "button primary";
            container.appendChild(link);
            container.appendChild(document.createElement("br"));
        }
    }

    async function loadDownloads(document, fetch, apiBaseUrl) {
        const container = document.getElementById("download-button");
        try {
            const response = await fetch(`${apiBaseUrl}/clients/`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            renderDownloads(document, container, await response.json(), apiBaseUrl);
        } catch (_error) {
            container.replaceChildren();
            const message = document.createElement("p");
            message.textContent = "Failed to load download options. Please try again later.";
            container.appendChild(message);
        }
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = { renderDownloads, loadDownloads };
    }
    if (root.document) {
        root.document.addEventListener("DOMContentLoaded", () =>
            loadDownloads(root.document, root.fetch.bind(root), root.ParseTrailConfig.apiBaseUrl));
    }
})(typeof window !== "undefined" ? window : globalThis);
