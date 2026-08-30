(function (global) {
	"use strict";

	function requiredUrl(config, name) {
		var value = config && config[name];
		if (typeof value !== "string" || value.length === 0) {
			throw new Error("Missing ParseTrail runtime configuration: " + name);
		}

		var parsed = new URL(value);
		if (
			(parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
			parsed.username ||
			parsed.password ||
			parsed.search ||
			parsed.hash
		) {
			throw new Error("Invalid ParseTrail runtime URL: " + name);
		}
		return parsed.href.replace(/\/$/, "");
	}

	var raw = global.__PARSETRAIL_CONFIG__;
	var config = Object.freeze({
		apiBaseUrl: requiredUrl(raw, "apiBaseUrl"),
		accountUrl: requiredUrl(raw, "accountUrl"),
		githubUrl: requiredUrl(raw, "githubUrl")
	});
	global.ParseTrailConfig = config;

	document.addEventListener("DOMContentLoaded", function () {
		document.querySelectorAll(".nav-github").forEach(function (element) {
			element.href = config.githubUrl;
		});
		document.querySelectorAll(".nav-login").forEach(function (element) {
			element.href = config.accountUrl;
		});
	});
})(window);
