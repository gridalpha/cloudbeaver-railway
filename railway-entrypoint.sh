#!/bin/bash
# Prepare the Railway volume, kick off the one-shot connection seeder, then hand
# over to the image's own launcher, which chowns the workspace and drops to the
# dbeaver user.
set -euo pipefail

cd /opt/cloudbeaver

WORKSPACE="${PWD}/workspace"
mkdir -p "${WORKSPACE}"

# Every Railway volume ships a lost+found at its mount root. CloudBeaver
# enumerates the workspace directory looking for projects, so it must not be
# there. Railway's own managed templates do the same thing.
rm -rf "${WORKSPACE}/lost+found" || true

chown -R "${DBEAVER_UID:-8978}:${DBEAVER_GID:-8978}" "${WORKSPACE}"

# Register the bundled database as a shared connection the first time this
# workspace boots. Runs behind the server so the health check is never blocked;
# it is a no-op on every later deploy.
if [ -n "${CB_SEED_CONNECTION_HOST:-}" ]; then
    /opt/cloudbeaver/railway-seed-connection.py &
fi

exec ./launch-product.sh "$@"
