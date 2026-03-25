#!/bin/bash

set -e

ldconfig
export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH}"

if [ $# -eq 0 ]; then
    : "${HOST:=0.0.0.0}"
    : "${PORT:=18000}"
    : "${ATLASWORKS_WORKERS:=1}"
    : "${ATLASWORKS_THREADS:=4}"
    : "${ATLASWORKS_TIMEOUT:=600}"
    set -- gunicorn \
        --bind "${HOST}:${PORT}" \
        --workers "${ATLASWORKS_WORKERS}" \
        --threads "${ATLASWORKS_THREADS}" \
        --worker-class gthread \
        --timeout "${ATLASWORKS_TIMEOUT}" \
        app:app
fi

exec "$@"
