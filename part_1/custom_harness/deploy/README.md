# Deployment hand-off

The production topology is OCI backend + Oracle AI Database 26ai, with the lightweight
Next.js client in `frontend/` deployed to Vercel. `python-oracledb` uses thin mode; a
wallet is optional for a TLS connection string and no Oracle client install is needed.

## Complete local stack (Docker Compose)

Docker Desktop needs at least the resources required by Oracle AI Database Free. From
this directory:

```bash
export ANTHROPIC_API_KEY='...'
export E2B_API_KEY='...'
export LANGSMITH_API_KEY='...'
docker compose up --build
```

Compose pulls Oracle's `container-registry.oracle.com/database/free:latest-lite`
image, exposes `FREEPDB1` on port 1521, stores data in `erpa-oracle-data`, bootstraps
the `AGENT` schema and fixtures, then starts ERPA on port 8000. The app startup rejects
a database older than the OAMP 26.6-compatible Oracle AI Database 26ai release.

Useful checks:

```bash
docker compose ps
curl http://127.0.0.1:8000/api/foundation/status
curl http://127.0.0.1:8000/api/cache/status
curl http://127.0.0.1:8000/api/the_loop/status
```

Stop containers without deleting persisted database state with `docker compose down`.
Only `docker compose down --volumes` removes the workshop database volume.

## Portable backend image

From the repository root:

```bash
docker build -f part_1/custom_harness/appbook/Dockerfile -t erpa-custom .
docker run --env-file .env -p 8000:8000 erpa-custom
```

Cloud Run, Railway and Fly can use the same image. In OCI, place the container and DB in
the same region/private network. Set `ERPA_MODE=live`, `ORA_DSN`, `ORA_AGENT_USER` and
`ORA_AGENT_PWD`; for Autonomous Database, also inject `ORA_WALLET_LOCATION` and
`ORA_WALLET_PASSWORD`. The live harness requires `ANTHROPIC_API_KEY`, `E2B_API_KEY`,
and `LANGSMITH_API_KEY`. Never bake a wallet or `.env` into the image.

`bootstrap_oracle.py` installs the scheduler job automatically in Compose. For an
externally provisioned database, run `oracle_scheduler.sql` once. It queues the
synthetic `Morning brief.` input; the worker invokes the exact graph used by interactive
chat and persists in-app delivery.

## Vercel

Set `NEXT_PUBLIC_ERPA_API` to the pre-provisioned backend, then run `vercel --prod` from
`frontend/`. The client has no server state and is intentionally small enough for the
live deploy to finish comfortably inside two minutes.
