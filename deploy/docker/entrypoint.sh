#!/bin/bash

set -e

ldconfig
export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH}"

if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone || true
fi

if [ $# -eq 0 ]; then
    if [ "${ATLASWORKS_ROLE:-api}" = "worker" ]; then
        set -- python3 /app/services/tiling/worker.py
    elif [ "${ATLASWORKS_ROLE:-api}" = "publisher" ]; then
        cd /app/services/publisher
        : "${HOST:=0.0.0.0}"
        : "${PORT:=18001}"
        : "${ATLASWORKS_PUBLISHER_WORKERS:=1}"
        : "${ATLASWORKS_PUBLISHER_THREADS:=4}"
        : "${ATLASWORKS_TIMEOUT:=600}"
        set -- gunicorn \
            --bind "${HOST}:${PORT}" \
            --workers "${ATLASWORKS_PUBLISHER_WORKERS}" \
            --threads "${ATLASWORKS_PUBLISHER_THREADS}" \
            --worker-class gthread \
            --timeout "${ATLASWORKS_TIMEOUT}" \
            app:app
    else
        cd /app/services/control
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
fi

exec "$@"
