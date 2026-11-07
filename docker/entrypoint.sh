#!/bin/sh
# Select the Python process from the first argument. Cloud Run passes the port in $PORT.
set -eu
cmd="${1:-core}"
[ "$#" -gt 0 ] && shift
case "$cmd" in
  core)
    export CORE_PORT="${PORT:-${CORE_PORT:-8080}}"
    exec python -m pramana_core "$@"
    ;;
  sim)
    export SIM_PORT="${PORT:-${SIM_PORT:-8080}}"
    exec python -m pramana_sim "$@"
    ;;
  migrate)
    exec python -m alembic -c /app/services/core/alembic.ini upgrade head
    ;;
  *)
    exec "$cmd" "$@"
    ;;
esac
