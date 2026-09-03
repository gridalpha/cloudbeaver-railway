# CloudBeaver on Railway

A one-layer image over [`dbeaver/cloudbeaver`](https://hub.docker.com/r/dbeaver/cloudbeaver)
(CloudBeaver Community, Apache-2.0) that makes it deployable on Railway without
any manual first-run steps.

The published image is already configured entirely by `CLOUDBEAVER_*` environment
variables, and CloudBeaver bootstraps its own administrator from `CB_SERVER_NAME`,
`CB_ADMIN_NAME` and `CB_ADMIN_PASSWORD`. This layer adds only what a Railway
variable cannot express:

- **Volume preparation.** Every Railway volume ships a `lost+found` at its mount
  root, and CloudBeaver enumerates its workspace directory looking for projects.
  The entrypoint removes it and chowns the workspace before the image's own
  launcher takes over.
- **A health endpoint the Railway prober can pass.** `forceHttps` is what gives
  CloudBeaver's session cookie its `Secure` flag, and it decides "was this HTTPS?"
  from `X-Forwarded-Proto` — which the prober, talking straight to the container,
  never sends, so every path answers 302. `railway-healthz.py` serves `$PORT` for
  the prober and replays CloudBeaver's own `/status` with the headers the edge
  would have added, so the check still tests the real server.
- **A pre-registered database connection.** CloudBeaver keeps connection
  credentials in its own encrypted credential store, so no config file can carry
  them. `railway-seed-connection.py` registers the project's database as a shared
  connection through CloudBeaver's GraphQL API once the server is up, guarded by a
  marker on the volume so a later edit or deletion is never reverted.

Neither step blocks startup, and a failed seed is logged and ignored — the
deployment stands on its own.

## Environment variables

| Variable | Purpose |
|---|---|
| `PORT` | `8080` — the health shim's port, which is what Railway probes |
| `CLOUDBEAVER_WEB_SERVER_PORT` | `8978` — CloudBeaver's own port, and the public domain's target port |
| `CLOUDBEAVER_FORCE_HTTPS` | `true` — gives the session cookie its `Secure` flag |
| `CB_SERVER_NAME` | any non-empty value; setting it is what skips the first-run setup wizard |
| `CB_ADMIN_NAME`, `CB_ADMIN_PASSWORD` | the administrator created on first boot |
| `CLOUDBEAVER_APP_ANONYMOUS_ACCESS_ENABLED` | `false` — the image default is `true`, which would leave the UI open |
| `CB_SEED_CONNECTION_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_PASSWORD` | the database to register; leave `_HOST` unset to seed nothing |
| `CB_SEED_CONNECTION_NAME` | connection label, default `Railway Postgres` |
| `CB_SEED_CONNECTION_DRIVER` | driver id suffix, default `postgres-jdbc` |

Mount a volume at `/opt/cloudbeaver/workspace`, point the public domain at port
`8978`, and set the health check to `/status`.
