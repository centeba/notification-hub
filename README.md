# notification-hub

A multi-channel **notification service** for Python — email, SMS, and webhooks
behind one API, with routing rules, delivery history, per-user preferences, and
an **agentic AI layer** (built on [smart-llm](https://github.com/centeba/smart-llm)).
Standalone and dependency-clean (no host-platform coupling).

## Features

- **Multi-channel delivery** — email (SMTP / SES), SMS (Twilio / SNS), and signed
  outbound webhooks, each behind a uniform ingest + delivery pipeline.
- **Routing rules** — event-driven rules decide which channels fire, with
  priorities, conditions, and recipient strategies.
- **Durable workflows** — delivery orchestration runs on [Temporal](https://temporal.io)
  for retries and exactly-once semantics.
- **Preferences & history** — per-user channel opt-in and a queryable delivery
  log (status, channel, event type, timestamps).
- **Agentic AI layer** — agents, skills, tool-policy gating, usage/budgets, and
  multi-provider LLM access via **smart-llm** (Anthropic / OpenAI / Gemini /
  OpenRouter).
- **Hardened edges** — HMAC-signed webhooks, an SSRF egress guard on outbound
  requests, and an optional per-IP rate limiter.
- **Observability** — structured JSON logs, Prometheus `/metrics`, OpenTelemetry
  traces, and deep `/healthz` readiness — all opt-in (via smart-llm's rails).

## Processes

One image, several process types (selected by the CLI subcommand):

| Command | Port | Role |
|---|---|---|
| `integration-hub start-api` | 8001 | Orchestration API (rules, logs, preferences, AI) |
| `integration-hub start-email` | 8002 | Email delivery service |
| `integration-hub start-sms` | 8003 | SMS delivery service |
| `integration-hub start-webhook` | 8004 | Webhook delivery service |
| `integration-hub start-worker` | — | Temporal worker (delivery workflows) |
| `integration-hub start-mcp` | — | MCP tool server (stdio) |
| `integration-hub migrate` | — | Run Alembic migrations to head |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[test]"                         # pulls smart-llm from git + deps
cp .env.example .env                             # then edit secrets / DB / Redis
integration-hub migrate                          # create the schema
integration-hub start-api                        # http://localhost:8001
```

Requires Postgres, Redis, and (for delivery workflows) Temporal — see
[`.env.example`](.env.example). `docker build .` produces a single image that
runs any of the processes above.

## Admin UIs

Two optional front-ends render the same views — **dashboard, delivery history,
routing rules, and preferences** — over the API:

- [`flutter_package/`](flutter_package) — a Flutter/Dart package (`notification_hub_ui`).
- [`react-admin/`](react-admin) — a Vite + React + TypeScript app.

Each has its own README.

## Documentation

- [Requirements](docs/REQUIREMENTS.md) — scope and acceptance criteria.
- [Design](docs/DESIGN.md) — architecture, channels, workflows, safety model.
- [User Guide](docs/USER_GUIDE.md) — install, configure, run, migrate, extend.
- [Integrations Setup Guide](docs/INTEGRATIONS.md) — per-connector setup (Gmail, Outlook, Datadog, …), credentials, and support status.

## Relationship to smart-llm

The AI layer is **not vendored** — notification-hub depends on the standalone
[`smart-llm`](https://github.com/centeba/smart-llm) package (pinned by git ref in
[`pyproject.toml`](pyproject.toml)). See the User Guide's "Updating smart-llm" for
how to bump the pin.

## Layout

- `src/integration_hub_backend/` — the service (api, email, sms, webhook, mcp,
  workflows, `_platform` vendored utilities).
- `flutter_package/`, `react-admin/` — the admin UIs.
- `docs/` — design and usage notes.
- `tests/` — the suite (`pytest`).

## License

MIT — see [`LICENSE`](LICENSE).
