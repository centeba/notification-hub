# notification-hub — User Guide

Install, configure, run, migrate, and extend notification-hub. See
[`REQUIREMENTS.md`](REQUIREMENTS.md) for scope and [`DESIGN.md`](DESIGN.md) for
architecture.

## Install

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[test]"        # resolves smart-llm from git + all runtime deps
```

Installing needs `git` on PATH (smart-llm is a git dependency) and a C toolchain
for `asyncpg`/`psycopg`.

## Configure

Copy the example env and fill it in:

```bash
cp .env.example .env
```

Key settings (full list in [`.env.example`](../.env.example)):

| Env | Purpose |
|---|---|
| `DATABASE_URL` | Postgres DSN (`postgresql+asyncpg://…`) |
| `REDIS_HOST` / `REDIS_PORT` | Redis for cache / idempotency / rate limit |
| `TEMPORAL_HOST` / `TEMPORAL_PORT` | Temporal for delivery workflows |
| `SECRET_KEY`, `INTERNAL_SERVICE_SECRET`, `WEBHOOK_SECRET` | secrets (auto-generated in non-prod) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / … | LLM providers (via smart-llm) |

In production, `SECRET_KEY`, `INTERNAL_SERVICE_SECRET`, and
`FIELD_ENCRYPTION_KEY` are **required** — the service refuses to start without
them (they must be stable across restarts/replicas).

## Migrate

```bash
alembic upgrade head            # uses repo-root alembic.ini
```

This creates every table (events, rules, channels, templates, logs, preferences,
company settings, api-keys, webhooks, and the smart-llm AI tables). Evolve the
schema with `alembic revision --autogenerate -m "…"`.

## Run

```bash
integration-hub start-api       # orchestration API on :8001
integration-hub start-worker    # Temporal worker (delivery workflows)
integration-hub start-email     # :8002   (also start-sms :8003, start-webhook :8004)
integration-hub start-mcp       # MCP tool server (stdio)
```

Or build the image and run any process from it:

```bash
docker build -t notification-hub .
docker run --env-file .env -p 8001:8001 notification-hub          # start-api (default)
docker run --env-file .env notification-hub integration-hub start-worker
```

Behind a TLS-inspection proxy, pass your root CA as a BuildKit secret:

```bash
docker buildx build --secret id=extra_ca,src=/path/root-ca.crt -t notification-hub .
```

## Using the API

Base path `/api/v1`. Send an event, define rules, read the delivery log:

```bash
curl -X POST localhost:8001/api/v1/events/ingest -H 'content-type: application/json' \
  -d '{"event_type":"invoice.paid","payload":{"amount":42}}'

curl localhost:8001/api/v1/rules
curl 'localhost:8001/api/v1/logs?limit=50&status=failed'
curl localhost:8001/api/v1/preferences/me
```

Health: `GET /health` (liveness), `GET /healthz` (deep readiness).

## Admin UIs

Two front-ends render dashboard / history / rules / preferences over the API:

- **Flutter** — [`../flutter_package`](../flutter_package) (`notification_hub_ui`):
  point it at your API (`--dart-define=API_URL=…/api/v1`) and use `DashboardScreen`,
  `HistoryScreen`, `RulesScreen`, `PreferencesScreen`. Supply a translator via
  `MultiLangDelegate` if you localize.
- **React** — [`../react-admin`](../react-admin): `npm install && npm run dev`
  (dev-proxies `/api` to your service); `npm run build` for production.

## Extending

- **New channel / tool** — add an AI tool via smart-llm's `ActionTool` pattern, or
  a delivery channel process following `email` / `sms` / `webhook`.
- **Authorization** — register a checker so AI delegation is enforced:

  ```python
  from integration_hub_backend._platform import authz
  authz.set_authz_checker(my_async_checker)   # default is permissive standalone
  ```

- **Rate limiting** — set `RATE_LIMIT_REDIS_URL` to enable the per-IP limiter.

## Updating smart-llm

The AI layer is the public [`smart-llm`](https://github.com/centeba/smart-llm)
package, pinned by commit in [`pyproject.toml`](../pyproject.toml):

```toml
"smart-llm[db,observability] @ git+https://github.com/centeba/smart-llm@<commit>"
```

To pull upstream fixes, bump `<commit>` to a newer `main` SHA (or a tag) and
re-run the test suite. Pinning to a SHA keeps builds reproducible.

## Develop

```bash
ruff check . --select "E9,F5,F63,F7,F811,F401,I,UP015,UP017,UP028,UP035,UP041,RUF010,RUF022,E401,W"
ruff format --check .
mypy src
pytest                          # needs Postgres + Redis; Temporal is mocked
```

CI (`.github/workflows/ci.yml`) runs ruff (blocking + advisory), mypy strict,
pytest (with Postgres/Redis services), `flutter analyze`, and the React build.
