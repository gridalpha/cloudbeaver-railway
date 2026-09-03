#!/usr/bin/env python3
"""Health-check shim.

CloudBeaver's `forceHttps` is what gives the session cookie its `Secure` flag,
but it decides "was this request HTTPS?" from X-Forwarded-Proto — which Railway's
health prober, talking straight to the container, does not send. The prober
therefore gets a 302 on every path and the deployment never goes healthy.

This serves `$PORT` for the prober alone and replays the request against
CloudBeaver's own `/status` with the headers the edge would have added, so the
check still tests the real server rather than a static marker. Public traffic is
unaffected: the domain targets CloudBeaver's port directly.
"""

import http.server
import json
import os
import socketserver
import sys
import urllib.request

UPSTREAM_PORT = os.environ.get("CLOUDBEAVER_WEB_SERVER_PORT", "8978")
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
UPSTREAM = "http://127.0.0.1:%s/status" % UPSTREAM_PORT
HEADERS = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "localhost"}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            request = urllib.request.Request(UPSTREAM, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=10) as response:
                healthy = response.status == 200
                body = response.read()
        except Exception as error:  # noqa: BLE001
            healthy, body = False, json.dumps({"health": "down", "error": str(error)}).encode()
        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if str(LISTEN_PORT) == str(UPSTREAM_PORT):
        print("[railway-healthz] PORT equals the CloudBeaver port, not starting", flush=True)
        sys.exit(0)
    print("[railway-healthz] probing %s from :%d" % (UPSTREAM, LISTEN_PORT), flush=True)
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
