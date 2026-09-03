# CloudBeaver Community on Railway.
#
# The published image is already fully env-var configurable, so this layer exists
# only for the two things a Railway variable cannot express:
#
#   1. preparing the mounted workspace volume (Railway volumes always ship a
#      lost+found directory, which DBeaver's workspace scanner would see beside
#      the projects), and
#   2. answering Railway's health prober, which sends no X-Forwarded-Proto and so
#      is 302'd by the forceHttps setting that gives the session cookie its
#      Secure flag, and
#   3. registering the bundled Postgres as a shared connection on first boot,
#      through CloudBeaver's own GraphQL API — connection credentials live in
#      CloudBeaver's encrypted credential store and no config file can carry them.
FROM dbeaver/cloudbeaver:latest

USER root

# ubuntu:noble ships no python3; the seeder needs the standard library only.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends python3; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c 'import json, urllib.request, http.cookiejar'

COPY railway-entrypoint.sh /opt/cloudbeaver/railway-entrypoint.sh
COPY railway-healthz.py /opt/cloudbeaver/railway-healthz.py
COPY railway-seed-connection.py /opt/cloudbeaver/railway-seed-connection.py

# Fail the build, not a crash loop, on a typo in either script.
RUN set -eux; \
    chmod +x /opt/cloudbeaver/railway-entrypoint.sh /opt/cloudbeaver/railway-seed-connection.py \
        /opt/cloudbeaver/railway-healthz.py; \
    bash -n /opt/cloudbeaver/railway-entrypoint.sh; \
    python3 -m py_compile /opt/cloudbeaver/railway-seed-connection.py /opt/cloudbeaver/railway-healthz.py

ENTRYPOINT ["/opt/cloudbeaver/railway-entrypoint.sh"]
