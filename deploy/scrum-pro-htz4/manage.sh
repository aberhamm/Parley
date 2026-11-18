#!/bin/sh
set -eu
cd /opt/apps/scrum-pro
exec docker compose --env-file .env --env-file image.env -f compose.yaml "$@"
