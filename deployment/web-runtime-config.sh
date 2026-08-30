#!/bin/sh

set -eu

output_path="/usr/share/nginx/html/runtime-config.js"
temporary_path=""

cleanup() {
    if [ -n "$temporary_path" ]; then
        rm -f "$temporary_path"
    fi
}

fail() {
    printf '%s\n' "ParseTrail runtime configuration error: $*" >&2
    exit 1
}

validate_url() {
    variable_name="$1"
    value="$2"

    [ -n "$value" ] || fail "$variable_name is required"
    case "$value" in
        http://* | https://*) ;;
        *) fail "$variable_name must be an absolute HTTP(S) URL" ;;
    esac

    # The narrow syntax rejects credentials, queries, fragments, whitespace, and
    # JavaScript string delimiters before nginx starts.
    if ! printf '%s\n' "$value" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~:/%+,=&-]*)?$'; then
        fail "$variable_name is not a supported public HTTP(S) URL"
    fi
}

trap cleanup EXIT HUP INT TERM

validate_url BACKEND_HOST "${BACKEND_HOST:-}"
validate_url FRONTEND_HOST "${FRONTEND_HOST:-}"
validate_url GITHUB_URL "${GITHUB_URL:-}"

temporary_path="$(mktemp "${output_path}.tmp.XXXXXX")"
printf '%s\n' \
    'window.__PARSETRAIL_CONFIG__ = Object.freeze({' \
    "  apiBaseUrl: \"${BACKEND_HOST}\"," \
    "  accountUrl: \"${FRONTEND_HOST}\"," \
    "  githubUrl: \"${GITHUB_URL}\"" \
    '});' >"$temporary_path"
chmod 0444 "$temporary_path"
mv "$temporary_path" "$output_path"
temporary_path=""
