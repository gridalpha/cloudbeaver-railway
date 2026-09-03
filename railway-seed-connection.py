#!/usr/bin/env python3
"""Register the project's bundled database as a shared CloudBeaver connection.

CloudBeaver keeps connection credentials in its own encrypted credential store,
so a connection cannot be seeded from a config file — its GraphQL API is the
only way in. This runs once per workspace, guarded by a marker on the volume, so
an operator who later edits or deletes the connection keeps their change.

Every failure is logged and swallowed: a deployment must never fail over a
convenience connection.
"""

import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HOME = "/opt/cloudbeaver"
MARKER = os.path.join(HOME, "workspace", ".railway-connection-seeded")
PORT = os.environ.get("CLOUDBEAVER_WEB_SERVER_PORT", "8978")
BASE = "http://127.0.0.1:%s" % PORT
GQL = BASE + "/api/gql"
STATUS = BASE + "/status"

ADMIN_USER = os.environ.get("CB_ADMIN_NAME", "")
ADMIN_PASSWORD = os.environ.get("CB_ADMIN_PASSWORD", "")

CONN_NAME = os.environ.get("CB_SEED_CONNECTION_NAME", "Railway Postgres")
CONN_HOST = os.environ.get("CB_SEED_CONNECTION_HOST", "")
CONN_PORT = os.environ.get("CB_SEED_CONNECTION_PORT", "5432")
CONN_DATABASE = os.environ.get("CB_SEED_CONNECTION_DATABASE", "railway")
CONN_USER = os.environ.get("CB_SEED_CONNECTION_USER", "")
CONN_PASSWORD = os.environ.get("CB_SEED_CONNECTION_PASSWORD", "")
CONN_DRIVER = os.environ.get("CB_SEED_CONNECTION_DRIVER", "postgres-jdbc")


def client_password(plaintext):
    """CloudBeaver's browser client sends MD5(password) in uppercase hex, and the
    server hashes that again before comparing — so the plaintext never matches."""
    return hashlib.md5(plaintext.encode("utf-8")).hexdigest().upper()


def log(message):
    print("[railway-seed] %s" % message, flush=True)


# CloudBeaver derives the request origin from X-Forwarded-Proto/Host and, with
# forceHttps on, redirects anything it reads as plain HTTP — including a loopback
# call. Present ourselves the way Railway's edge presents a browser.
FORWARDED = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "localhost",
}

class LoopbackCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    """forceHttps makes CloudBeaver mark its session cookie Secure, and the
    standard policy then refuses to send it back over our plain-HTTP loopback
    call — every request would arrive as a fresh anonymous session."""

    def return_ok_secure(self, cookie, request):
        return True


opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar(LoopbackCookiePolicy()))
)


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        GQL,
        data=body,
        headers=dict(FORWARDED, **{
            "Content-Type": "application/json",
            "Accept": "application/json",
        }),
    )
    with opener.open(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"])[:800])
    return payload["data"]


def wait_for_server(deadline_seconds=600):
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(STATUS, headers=FORWARDED)
            with opener.open(request, timeout=10) as response:
                if response.status == 200 and b'"health"' in response.read():
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def pick_driver():
    drivers = gql("query { driverList { id name } }")["driverList"]
    for driver in drivers:
        if driver["id"].split(":")[-1] == CONN_DRIVER:
            return driver["id"]
    for driver in drivers:
        if CONN_DRIVER in driver["id"]:
            return driver["id"]
    raise RuntimeError("no driver matching %r among %d drivers" % (CONN_DRIVER, len(drivers)))


def pick_project():
    projects = gql("query { listProjects { id global canEditDataSources } }")["listProjects"]
    for project in projects:
        if project["global"] and project["canEditDataSources"]:
            return project["id"]
    for project in projects:
        if project["canEditDataSources"]:
            return project["id"]
    raise RuntimeError("no writable project among %d" % len(projects))


def seed():
    gql("mutation { openSession { createTime } }")
    gql(
        "query login($u: Object) { authLogin(provider: \"local\", credentials: $u) { authId } }",
        {"u": {"user": ADMIN_USER, "password": client_password(ADMIN_PASSWORD)}},
    )
    project_id = pick_project()
    driver_id = pick_driver()
    log("project=%s driver=%s" % (project_id, driver_id))

    existing = gql(
        "query conns($p: ID) { userConnections(projectId: $p) { id name } }",
        {"p": project_id},
    )["userConnections"]
    for connection in existing:
        if connection["name"] == CONN_NAME:
            log("connection %r already exists" % CONN_NAME)
            return

    config = {
        "name": CONN_NAME,
        "description": "Provisioned by the Railway template.",
        "driverId": driver_id,
        "host": CONN_HOST,
        "port": str(CONN_PORT),
        "databaseName": CONN_DATABASE,
        "configurationType": "MANUAL",
        "authModelId": "native",
        "saveCredentials": True,
        # sharedCredentials routes through a secret controller the Community
        # edition does not ship ("Session secret controller not found").
        "sharedCredentials": False,
        "credentials": {"userName": CONN_USER, "userPassword": CONN_PASSWORD},
    }
    result = gql(
        "mutation create($c: ConnectionConfig!, $p: ID) {"
        " createConnection(config: $c, projectId: $p) { id name } }",
        {"c": config, "p": project_id},
    )
    log("created connection %s" % result["createConnection"]["id"])


def main():
    if os.path.exists(MARKER):
        return
    if not (ADMIN_USER and ADMIN_PASSWORD and CONN_HOST and CONN_USER):
        log("incomplete configuration, nothing to seed")
        return
    if not wait_for_server():
        log("server did not become ready, skipping")
        return
    for attempt in range(1, 9):
        try:
            seed()
            with open(MARKER, "w") as handle:
                handle.write(CONN_NAME + "\n")
            return
        except Exception as error:  # noqa: BLE001 - never fail the container
            message = str(error)
            log("attempt %d failed: %s" % (attempt, message[:300]))
            # CloudBeaver's brute-force protection blocks a user for a stated
            # number of seconds; sleeping less than that just burns an attempt.
            blocked = re.search(r"login for this user for (\d+) seconds", message)
            time.sleep(int(blocked.group(1)) + 10 if blocked else 30)
    log("giving up; add the connection from the Connections admin page")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        log("unexpected error: %s" % error)
    sys.exit(0)
