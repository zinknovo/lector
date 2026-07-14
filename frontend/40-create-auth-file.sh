#!/bin/sh
set -eu

if [ -z "${FRONTEND_USERNAME:-}" ] || [ -z "${FRONTEND_PASSWORD:-}" ]; then
    echo "FRONTEND_USERNAME and FRONTEND_PASSWORD must be configured" >&2
    exit 1
fi

htpasswd -bc /etc/nginx/.htpasswd "$FRONTEND_USERNAME" "$FRONTEND_PASSWORD" >/dev/null
