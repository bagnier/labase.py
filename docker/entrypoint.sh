#!/bin/sh
set -e

SSL_ARGS=""
if [ -n "$SSL_CERTFILE" ] && [ -n "$SSL_KEYFILE" ]; then
    SSL_ARGS="--certfile $SSL_CERTFILE --keyfile $SSL_KEYFILE"
fi

# shellcheck disable=SC2086
exec uv run hypercorn apps.main:app --bind 0.0.0.0:8000 $SSL_ARGS "$@"
