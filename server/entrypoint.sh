#!/bin/sh
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

mkdir -p "${SHEPHERD_DATA:-/data}"
chown "$PUID:$PGID" "${SHEPHERD_DATA:-/data}"

exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
