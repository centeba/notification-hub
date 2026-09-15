#!/bin/sh
# Container entrypoint for integration-hub. One image serves api, worker,
# and the email/sms/webhook stub services (docker-compose / Railway pick
# which via a command override), so this only runs the CLI's own ``migrate``
# subcommand (alembic upgrade head, via cli.py's alembic.ini auto-discovery)
# when the command being started is ``start-api`` — the other targets don't
# own migrations and would just add a redundant (if idempotent) DB round
# trip on every boot otherwise.
set -e

# Boot-time DB retry: on some platforms (e.g. Railway private networking) the
# database host isn't resolvable/connectable the instant the container starts,
# so a migration that connects immediately fails with "could not translate host
# name" / connection refused and the container crashes. Retry so it self-heals.
_retry_migrate() {
  n=0; max=40
  until "$@"; do
    n=$((n + 1))
    if [ "$n" -ge "$max" ]; then
      echo "[entrypoint] migrate failed after $max attempts" >&2
      exit 1
    fi
    echo "[entrypoint] migrate attempt $n failed (DB not ready?); retry in 3s..."
    sleep 3
  done
}

# No explicit `cd` here — the WORKDIR differs by build (compose ends at
# /app/services/integration-hub/notification_hub_backend); ``integration-hub
# migrate`` already does its own alembic.ini discovery (cli.py checks
# several candidate paths, falling back to Path.cwd()), so whichever
# WORKDIR Docker leaves us in at container start is fine.

case "$2" in
  start-api)
    echo "[entrypoint] integration-hub migrate"
    _retry_migrate integration-hub migrate
    ;;
esac

echo "[entrypoint] starting: $*"
exec "$@"
