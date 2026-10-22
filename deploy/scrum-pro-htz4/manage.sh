#!/bin/sh
set -eu
cd /opt/apps/scrum-pro
exec docker compose --env-file .env -f compose.yaml "$@"
