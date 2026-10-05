#!/bin/sh
set -e

SSL_ARGS=""
if [ -n "$SSL_CERTFILE" ] && [ -n "$SSL_KEYFILE" ]; then
    SSL_ARGS="--certfile $SSL_CERTFILE --keyfile $SSL_KEYFILE"
fi

# `exec`: Hypercorn is PID 1 and gets SIGTERM itself, to drain requests before exiting.
GRACEFUL_ARGS="--graceful-timeout ${GRACEFUL_TIMEOUT:-25}"

# shellcheck disable=SC2086
exec uv run hypercorn apps.main:app \
    --bind "0.0.0.0:${PORT:-8000}" \
    $SSL_ARGS $GRACEFUL_ARGS "$@"
